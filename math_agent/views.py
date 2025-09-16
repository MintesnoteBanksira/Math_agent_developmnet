from django.shortcuts import render, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView
from django.http import JsonResponse, HttpResponse
from django.db import transaction
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
import threading
import queue
import time
from .utils.similarity_utils import SIMILARITY_THRESHOLD

# Create your views here.

def problem_generation_worker(worker_id, task_queue, result_queue, pipeline, taxonomy_file, batch_id, stats_lock, stats):
    """
    Worker function for generating problems in parallel.
    
    Args:
        worker_id: Unique identifier for this worker
        task_queue: Queue containing generation tasks
        result_queue: Queue to put completed problems
        pipeline: Pipeline configuration
        taxonomy_file: Taxonomy data for subject/topic selection
        batch_id: Batch ID for database operations
        stats_lock: Thread lock for shared statistics
        stats: Shared statistics dictionary
    """
    while True:
        try:
            # Get task from queue (blocking with timeout)
            task = task_queue.get(timeout=1)
            if task is None:  # Shutdown signal
                break
                
            attempt_id = task['attempt_id']
            print(f"\n[Worker {worker_id}] Starting attempt {attempt_id}")
            print("=" * 50)
            
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
                
                # Generate problem
                print(f"[Worker {worker_id}] Calling generator for {subject} - {topic}...")
                question, answer, hints, embedding, similar_problems, generator_cost = generate_problem(pipeline['generator'], taxonomy=taxonomy)
                problem_cost += generator_cost
                print(f"[Worker {worker_id}] Generator result:\nQuestion: {question}\nAnswer: {answer}\nCost: ${generator_cost}")
                
                # Check problem validity
                print(f"[Worker {worker_id}] Calling checker...")
                is_valid, rejection_reason, corrected_hints, checker_cost = check_problem(question, answer, hints, pipeline['checker'])
                problem_cost += checker_cost
                print(f"[Worker {worker_id}] Checker result: {'Valid' if is_valid else 'Invalid'}\nCost: ${checker_cost}")
                
                if not is_valid:
                    print(f"[Worker {worker_id}] Rejection reason: {rejection_reason}")
                    # Create discarded problem with transaction safety
                    with transaction.atomic():
                        problem = Problem.objects.create(
                            subject=subject,
                            topic=topic,
                            question=question,
                            answer=answer,
                            hints=hints,
                            rejection_reason=rejection_reason,
                            status='discarded',
                            batch_id=batch_id,
                            problem_embedding=embedding,
                            similar_problems=similar_problems,
                            cost=problem_cost
                        )
                        
                        # Update similar problems' similar_problems field
                        for sim_id, sim_score in similar_problems.items():
                            try:
                                sim_prob = Problem.objects.select_for_update().get(id=sim_id)
                                sim_dict = sim_prob.similar_problems or {}
                                sim_dict[str(problem.id)] = sim_score
                                sim_prob.similar_problems = sim_dict
                                sim_prob.save(update_fields=['similar_problems'])
                            except Problem.DoesNotExist:
                                continue
                    
                    # Update shared stats
                    with stats_lock:
                        stats['discarded'] += 1
                        stats['total_cost'] += problem_cost
                        stats['attempts'] += 1
                    
                    result_queue.put({
                        'type': 'discarded',
                        'problem_id': problem.id,
                        'cost': problem_cost,
                        'attempt_id': attempt_id,
                        'worker_id': worker_id
                    })
                    
                else:
                    # Use corrected hints if provided
                    if corrected_hints:
                        print(f"[Worker {worker_id}] Using corrected hints from checker")
                        hints = corrected_hints

                    # Test with target
                    print(f"[Worker {worker_id}] Calling target...")
                    target_result, target_cost = test_with_target(question, pipeline['target'])
                    problem_cost += target_cost
                    print(f"[Worker {worker_id}] Target result:\n{target_result}\nCost: ${target_cost}")
                    
                    # Judge the solution
                    print(f"[Worker {worker_id}] Calling judge...")
                    is_solved, judge_cost = judge_solution(target_result, answer, pipeline['judge'])
                    problem_cost += judge_cost
                    print(f"[Worker {worker_id}] Judge result: {'Solved' if is_solved else 'Not Solved'}\nCost: ${judge_cost}")
                    
                    # Create problem with appropriate status and transaction safety
                    status = 'solved' if is_solved else 'valid'
                    with transaction.atomic():
                        problem = Problem.objects.create(
                            subject=subject,
                            topic=topic,
                            question=question,
                            answer=answer,
                            hints=hints,
                            status=status,
                            batch_id=batch_id,
                            problem_embedding=embedding,
                            similar_problems=similar_problems,
                            cost=problem_cost
                        )
                        
                        # Update similar problems' similar_problems field
                        for sim_id, sim_score in similar_problems.items():
                            try:
                                sim_prob = Problem.objects.select_for_update().get(id=sim_id)
                                sim_dict = sim_prob.similar_problems or {}
                                sim_dict[str(problem.id)] = sim_score
                                sim_prob.similar_problems = sim_dict
                                sim_prob.save(update_fields=['similar_problems'])
                            except Problem.DoesNotExist:
                                continue
                    
                    # Update shared stats
                    with stats_lock:
                        stats['total_cost'] += problem_cost
                        stats['attempts'] += 1
                        if status == 'valid':
                            stats['valid'] += 1
                        else:
                            stats['solved'] += 1
                    
                    result_queue.put({
                        'type': status,
                        'problem_id': problem.id,
                        'cost': problem_cost,
                        'attempt_id': attempt_id,
                        'worker_id': worker_id
                    })
                    
                    print(f"[Worker {worker_id}] Valid problem count: {stats['valid']}/{stats['target_valid']}")
                
            except Exception as e:
                print(f"[Worker {worker_id}] Error in attempt {attempt_id}: {str(e)}")
                print(f"[Worker {worker_id}] Skipping this attempt and continuing with next generation...")
                
                # Update shared stats
                with stats_lock:
                    stats['attempts'] += 1
                
                result_queue.put({
                    'type': 'error',
                    'error': str(e),
                    'attempt_id': attempt_id,
                    'worker_id': worker_id
                })
            
            # Mark task as done
            task_queue.task_done()
            
        except queue.Empty:
            # Timeout waiting for task, check if we should continue
            continue
        except Exception as e:
            print(f"[Worker {worker_id}] Fatal error: {str(e)}")
            break

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

            print(f"\n🚀 Starting threaded problem generation with 10 workers")
            print(f"Target: {number_of_valid_needed} valid problems")
            print("=" * 60)

            # Threading setup
            NUM_WORKERS = 10
            task_queue = queue.Queue()
            result_queue = queue.Queue()
            stats_lock = threading.Lock()
            
            # Shared statistics
            stats = {
                'valid': 0,
                'solved': 0,
                'discarded': 0,
                'attempts': 0,
                'total_cost': 0.0,
                'target_valid': number_of_valid_needed,
                'completed': False
            }
            
            # Start worker threads
            workers = []
            for i in range(NUM_WORKERS):
                worker = threading.Thread(
                    target=problem_generation_worker,
                    args=(i + 1, task_queue, result_queue, pipeline, taxonomy_file, batch.id, stats_lock, stats),
                    daemon=True
                )
                worker.start()
                workers.append(worker)
                print(f"Started worker {i + 1}")
            
            # Add initial tasks to queue (start with 3x the target to ensure we have enough work)
            initial_tasks = number_of_valid_needed * 3
            for attempt_id in range(1, initial_tasks + 1):
                task_queue.put({'attempt_id': attempt_id})
            
            print(f"Added {initial_tasks} initial tasks to queue")
            
            # Monitor progress and add more tasks as needed
            last_status_time = time.time()
            status_interval = 10  # Print status every 10 seconds
            
            while stats['valid'] < number_of_valid_needed:
                try:
                    # Check for results
                    try:
                        result = result_queue.get(timeout=1)
                        if result['type'] in ['valid', 'solved', 'discarded']:
                            print(f"✅ [Worker {result['worker_id']}] Completed {result['type']} problem (Attempt {result['attempt_id']})")
                        elif result['type'] == 'error':
                            print(f"❌ [Worker {result['worker_id']}] Error in attempt {result['attempt_id']}: {result['error']}")
                        
                        result_queue.task_done()
                    except queue.Empty:
                        pass
                    
                    # Add more tasks if queue is getting low and we haven't reached target
                    if task_queue.qsize() < 5 and stats['valid'] < number_of_valid_needed:
                        # Add 10 more tasks
                        for i in range(10):
                            task_queue.put({'attempt_id': stats['attempts'] + i + 1})
                        print(f"Added 10 more tasks to queue (Queue size: {task_queue.qsize()})")
                    
                    # Print periodic status
                    current_time = time.time()
                    if current_time - last_status_time >= status_interval:
                        with stats_lock:
                            print(f"\n📊 Status Update:")
                            print(f"   Valid: {stats['valid']}/{number_of_valid_needed}")
                            print(f"   Solved: {stats['solved']}")
                            print(f"   Discarded: {stats['discarded']}")
                            print(f"   Total Attempts: {stats['attempts']}")
                            print(f"   Total Cost: ${stats['total_cost']:.4f}")
                            print(f"   Queue Size: {task_queue.qsize()}")
                            print(f"   Active Workers: {sum(1 for w in workers if w.is_alive())}")
                        last_status_time = current_time
                    
                    # Safety check - prevent infinite loop
                    if stats['attempts'] > number_of_valid_needed * 10:  # 10x safety factor
                        print(f"⚠️  Safety limit reached ({stats['attempts']} attempts). Stopping generation.")
                        break
                        
                except KeyboardInterrupt:
                    print("\n🛑 Generation interrupted by user")
                    break
            
            # Shutdown workers
            print("\n🔄 Shutting down workers...")
            for _ in range(NUM_WORKERS):
                task_queue.put(None)  # Shutdown signal
            
            # Wait for workers to finish
            for worker in workers:
                worker.join(timeout=5)
            
            # Process any remaining results
            while not result_queue.empty():
                try:
                    result = result_queue.get_nowait()
                    if result['type'] in ['valid', 'solved', 'discarded']:
                        print(f"✅ Final result: {result['type']} problem from worker {result['worker_id']}")
                    result_queue.task_done()
                except queue.Empty:
                    break
            
            # Update batch with final cost
            batch.batch_cost = stats['total_cost']
            batch.save(update_fields=['batch_cost'])
            
            print(f"\n🎉 Generation Complete!")
            print(f"   Valid Problems: {stats['valid']}")
            print(f"   Solved Problems: {stats['solved']}")
            print(f"   Discarded Problems: {stats['discarded']}")
            print(f"   Total Attempts: {stats['attempts']}")
            print(f"   Total Cost: ${stats['total_cost']:.4f}")
            print(f"   Success Rate: {(stats['valid'] / stats['attempts'] * 100):.1f}%" if stats['attempts'] > 0 else "N/A")

            return JsonResponse({
                'status': 'success',
                'batch_id': batch.id,
                'message': f'Successfully generated batch with {stats["valid"]} valid problems in {stats["attempts"]} attempts using {NUM_WORKERS} workers',
                'total_cost': stats['total_cost'],
                'stats': {
                    'valid': stats['valid'],
                    'solved': stats['solved'],
                    'discarded': stats['discarded'],
                    'attempts': stats['attempts'],
                    'success_rate': round(stats['valid'] / stats['attempts'] * 100, 1) if stats['attempts'] > 0 else 0
                }
            })

        except Exception as e:
            print(f"\n❌ Error occurred: {str(e)}")
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
