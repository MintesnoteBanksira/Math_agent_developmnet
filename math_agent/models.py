from django.db import models
from django.core.validators import MinValueValidator

# Create your models here.

class Batch(models.Model):
    name = models.CharField(max_length=255)
    taxonomy_json = models.JSONField()
    pipeline = models.JSONField()  # Dictionary of dictionaries for generator, hinter, checker, target, judge
    number_of_valid_needed = models.IntegerField(validators=[MinValueValidator(1)])
    batch_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0.00)  # Track total batch cost
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - Created: {self.created_at}"

    class Meta:
        verbose_name_plural = "Batches"

class Problem(models.Model):
    STATUS_CHOICES = [
        ('discarded', 'Discarded'),
        ('solved', 'Solved'),
        ('valid', 'Valid')
    ]

    subject = models.CharField(max_length=100)
    topic = models.CharField(max_length=100)
    question = models.TextField()
    answer = models.TextField()
    hints = models.JSONField()  # Dictionary of hints
    rejection_reason = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='problems')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    problem_embedding = models.JSONField(null=True, blank=True)
    similar_problems = models.JSONField(default=dict, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=6, default=0.00)  # Track cost up to 6 decimal places

    def __str__(self):
        return f"{self.subject} - {self.topic} - {self.status}"

    class Meta:
        verbose_name_plural = "Problems"
        ordering = ['-created_at']
