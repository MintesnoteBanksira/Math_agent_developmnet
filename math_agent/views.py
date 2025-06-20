from django.shortcuts import render, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView
from django.http import JsonResponse, HttpResponse
from .models import Batch, Problem
from .utils.generator import generate_problem
from .utils.hinter import generate_hints
from .utils.checker import check_problem
from .utils.target import test_with_target
from .utils.judge import judge_solution
from datetime import datetime
import json
import random
import csv
from .utils.similarity_utils import SIMILARITY_THRESHOLD

# Create your views here.

class GenerateView(View):
    def get(self, request):
        return render(request, 'math_agent/generate.html')

    def post(self, request):
        try:
            # Get parameters from request
            number_of_valid_needed = int(request.POST.get('number_of_valid_needed'))
            pipeline = json.loads(request.POST.get('pipeline'))
            taxonomy_file = json.loads(request.FILES.get('taxonomy_file').read().decode('utf-8'))

            # Create new batch
            batch = Batch.objects.create(
                name=f"Batch_{pipeline['target']['model']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                taxonomy_json=taxonomy_file,
                pipeline=pipeline,
                number_of_valid_needed=number_of_valid_needed
            )

            valid_count = 0
            attempt_count = 0
            batch_cost = 0.0
            
            while valid_count < number_of_valid_needed:
                attempt_count += 1
                print(f"\nAttempt {attempt_count}")
                print("=" * 50)
                
                # Reset cost for this problem
                problem_cost = 0.0
                
                try:
                    # Randomly select subject and topic from taxonomy
                    subject = random.choice(list(taxonomy_file.keys()))
                    topic = random.choice(taxonomy_file[subject])
                    
                    # Create taxonomy dict for generator
                    taxonomy = {
                        "subject": subject,
                        "topic": topic
                    }
                    
                    # Generate problem (now includes hints, embedding, similar_problems, cost)
                    print(f"Calling generator for {subject} - {topic}...")
                    question, answer, hints, embedding, similar_problems, generator_cost = generate_problem(pipeline['generator'], taxonomy=taxonomy)
                    problem_cost += generator_cost
                    print(f"Generator result:\nQuestion: {question}\nAnswer: {answer}\nHints: {json.dumps(hints, indent=2)}\nSimilar: {similar_problems}\nCost: ${generator_cost}")
                    
                    # Check problem validity
                    print("\nCalling checker...")
                    is_valid, rejection_reason, corrected_hints, checker_cost = check_problem(question, answer, hints, pipeline['checker'])
                    problem_cost += checker_cost
                    print(f"Checker result: {'Valid' if is_valid else 'Invalid'}\nCost: ${checker_cost}")
                    
                    if not is_valid:
                        print(f"Rejection reason: {rejection_reason}")
                        # Create discarded problem
                        problem = Problem.objects.create(
                            subject=subject,
                            topic=topic,
                            question=question,
                            answer=answer,
                            hints=hints,
                            rejection_reason=rejection_reason,
                            status='discarded',
                            batch=batch,
                            problem_embedding=embedding,
                            similar_problems=similar_problems,
                            cost=problem_cost
                        )
                        # Update batch cost
                        batch_cost += problem_cost
                        # Update similar problems' similar_problems field
                        for sim_id, sim_score in similar_problems.items():
                            try:
                                sim_prob = Problem.objects.get(id=sim_id)
                                sim_dict = sim_prob.similar_problems or {}
                                sim_dict[str(problem.id)] = sim_score
                                sim_prob.similar_problems = sim_dict
                                sim_prob.save(update_fields=['similar_problems'])
                            except Problem.DoesNotExist:
                                continue
                        continue
                    
                    # Use corrected hints if provided
                    if corrected_hints:
                        print("Using corrected hints from checker")
                        hints = corrected_hints

                    # Test with target
                    print("\nCalling target...")
                    target_result, target_cost = test_with_target(question, pipeline['target'])
                    problem_cost += target_cost
                    print(f"Target result:\n{target_result}\nCost: ${target_cost}")
                    
                    # Judge the solution
                    print("\nCalling judge...")
                    is_solved, judge_cost = judge_solution(target_result, answer, pipeline['judge'])
                    problem_cost += judge_cost
                    print(f"Judge result: {'Solved' if is_solved else 'Not Solved'}\nCost: ${judge_cost}")
                    
                    # Create problem with appropriate status
                    status = 'solved' if is_solved else 'valid'
                    problem = Problem.objects.create(
                        subject=subject,
                        topic=topic,
                        question=question,
                        answer=answer,
                        hints=hints,
                        status=status,
                        batch=batch,
                        problem_embedding=embedding,
                        similar_problems=similar_problems,
                        cost=problem_cost
                    )
                    # Update batch cost
                    batch_cost += problem_cost
                    # Update similar problems' similar_problems field
                    for sim_id, sim_score in similar_problems.items():
                        try:
                            sim_prob = Problem.objects.get(id=sim_id)
                            sim_dict = sim_prob.similar_problems or {}
                            sim_dict[str(problem.id)] = sim_score
                            sim_prob.similar_problems = sim_dict
                            sim_prob.save(update_fields=['similar_problems'])
                        except Problem.DoesNotExist:
                            continue
                    
                    if status == 'valid':
                        valid_count += 1
                        print(f"\nValid problem count: {valid_count}/{number_of_valid_needed}")
                
                except Exception as e:
                    print(f"Error in attempt {attempt_count}: {str(e)}")
                    print("Skipping this attempt and continuing with next generation...")
                    continue

            # Update batch with final cost
            batch.batch_cost = batch_cost
            batch.save(update_fields=['batch_cost'])

            return JsonResponse({
                'status': 'success',
                'batch_id': batch.id,
                'message': f'Successfully generated batch with {valid_count} valid problems in {attempt_count} attempts',
                'total_cost': batch_cost
            })

        except Exception as e:
            print(f"\nError occurred: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

class BatchListView(ListView):
    model = Batch
    template_name = 'math_agent/batches.html'
    context_object_name = 'batches'
    ordering = ['-created_at']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for batch in context['batches']:
            batch.stats = {
                'discarded': batch.problems.filter(status='discarded').count(),
                'solved': batch.problems.filter(status='solved').count(),
                'valid': batch.problems.filter(status='valid').count()
            }
        return context

class BatchDetailView(DetailView):
    model = Batch
    template_name = 'math_agent/batch_detail.html'
    context_object_name = 'batch'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stats'] = {
            'discarded': self.object.problems.filter(status='discarded').count(),
            'solved': self.object.problems.filter(status='solved').count(),
            'valid': self.object.problems.filter(status='valid').count()
        }
        
        # Calculate cost per valid problem
        valid_count = context['stats']['valid']
        if valid_count > 0:
            context['cost_per_problem'] = self.object.batch_cost / valid_count
        else:
            context['cost_per_problem'] = 0
        
        return context

class ProblemDetailView(DetailView):
    model = Problem
    template_name = 'math_agent/problem_detail.html'
    context_object_name = 'problem'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add batch information
        context['batch'] = self.object.batch
        # Add similar problems queryset
        similar_ids = list(map(int, self.object.similar_problems.keys())) if self.object.similar_problems else []
        context['similar_problems'] = Problem.objects.filter(id__in=similar_ids) if similar_ids else []
        context['similarity_scores'] = self.object.similar_problems if self.object.similar_problems else {}
        return context

class ProblemListView(ListView):
    model = Problem
    template_name = 'math_agent/problems.html'
    context_object_name = 'problems'

    def get_queryset(self):
        queryset = Problem.objects.all()
        batch_id = self.kwargs.get('batch_id')
        status = self.request.GET.get('status')

        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if status:
            queryset = queryset.filter(status=status)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['batch_id'] = self.kwargs.get('batch_id')
        context['status'] = self.request.GET.get('status')
        return context

class AllProblemsView(ListView):
    model = Problem
    template_name = 'math_agent/all_problems.html'
    context_object_name = 'problems'

    def get_queryset(self):
        queryset = Problem.objects.all()
        status = self.request.GET.get('status')
        
        if status:
            queryset = queryset.filter(status=status)
            
        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status'] = self.request.GET.get('status')
        return context

def export_problems_csv(request):
    """
    Export problems to CSV format.
    Accepts optional batch_id parameter to export problems from a specific batch.
    """
    # Get batch_id from query parameters
    batch_id = request.GET.get('batch_id')
    
    # Filter problems based on batch_id
    if batch_id:
        try:
            batch = Batch.objects.get(id=batch_id)
            problems = Problem.objects.filter(batch=batch)
            filename = f"batch_{batch_id}_problems_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        except Batch.DoesNotExist:
            return HttpResponse("Batch not found", status=404)
    else:
        problems = Problem.objects.all()
        filename = f"all_problems_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    # Create HTTP response with CSV content
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Create CSV writer
    writer = csv.writer(response)
    
    # Write header row
    writer.writerow(['ID', 'Subject', 'Topic', 'Question', 'Answer', 'Hints', 'Status', 'Similar Problems'])
    
    # Write data rows
    for problem in problems:
        # Format hints as they appear on frontend
        hints_text = ""
        if problem.hints:
            hints_list = []
            for hint_key, hint_value in problem.hints.items():
                hints_list.append(f"Hint {hint_key}: {hint_value}")
            hints_text = "; ".join(hints_list)
        
        # Format similar problems as they appear on frontend
        similar_text = ""
        if problem.similar_problems:
            similar_list = []
            for sim_id, sim_score in problem.similar_problems.items():
                similar_list.append(f"ID {sim_id}: {sim_score:.3f}")
            similar_text = "; ".join(similar_list)
        
        # Write row with all fields
        writer.writerow([
            problem.id,
            problem.subject,
            problem.topic,
            problem.question,
            problem.answer,
            hints_text,
            problem.status,
            similar_text
        ])
    
    return response
