import asyncio
import json
import os
import sys

from app.ai.assessor import assessor
from app.ai.providers import get_llm_provider

FIXTURES_DIR = "/app/tests/fixtures/transcripts"

ROLES = {
    "backend_engineer": [
        {"role": "assistant", "content": "Hello! I am your AI interviewer. Could you please introduce yourself and tell me about your recent experience?"},
        {"role": "candidate", "content": "Hi! I'm a backend engineer with 5 years of experience, mostly working with Python, FastAPI, and PostgreSQL. Recently I led a migration from monolith to microservices using Docker and Kubernetes."},
        {"role": "assistant", "content": "That sounds interesting. Can you explain how you handled database transactions across microservices?"},
        {"role": "candidate", "content": "We primarily used the saga pattern for distributed transactions. We had an orchestrator service that coordinated the steps, and if any step failed, it would trigger compensating transactions to rollback the previous steps. We used RabbitMQ for reliable message passing."}
    ],
    "data_scientist": [
        {"role": "assistant", "content": "Hello! Could you tell me about a recent machine learning model you deployed to production?"},
        {"role": "candidate", "content": "Yes, I recently built a churn prediction model. I used XGBoost for the classification. We had imbalanced data, so I applied SMOTE for oversampling and tuned hyperparameters using Optuna."},
        {"role": "assistant", "content": "How did you measure the performance of this model, considering the imbalanced dataset?"},
        {"role": "candidate", "content": "Accuracy wasn't useful due to the class imbalance, so I focused on the PR-AUC (Precision-Recall Area Under Curve). I also looked closely at the F1-score and the recall for the positive class since missing a churning customer was more expensive than a false positive."}
    ],
    "qa_engineer": [
        {"role": "assistant", "content": "Hi! Can you walk me through your approach to designing a test automation framework from scratch?"},
        {"role": "candidate", "content": "Sure. I usually start by selecting the right tools based on the tech stack. For a modern web app, I'd choose Playwright with TypeScript. I use the Page Object Model design pattern to keep the code maintainable, and integrate the tests into GitHub Actions for CI/CD."},
        {"role": "assistant", "content": "How do you handle test data management and flaky tests?"},
        {"role": "candidate", "content": "For test data, I prefer generating it dynamically via API before the test starts and cleaning it up after. To handle flakiness, I avoid hardcoded sleeps and use dynamic waits provided by Playwright. If a test is consistently flaky, I quarantine it until the root cause is fixed."}
    ],
    "devops_engineer": [
        {"role": "assistant", "content": "Hello! Can you describe your experience with Infrastructure as Code?"},
        {"role": "candidate", "content": "I have extensive experience with Terraform. I manage our AWS infrastructure using modular Terraform code, keeping state files in an S3 bucket with DynamoDB for locking. Everything is version-controlled and deployed via CI pipelines."},
        {"role": "assistant", "content": "What strategies do you use for zero-downtime deployments?"},
        {"role": "candidate", "content": "We primarily use blue-green deployments in Kubernetes. We deploy the new version alongside the old one, run automated smoke tests against the new version, and then switch the traffic over at the ingress controller level. If anything goes wrong, rolling back is instant."}
    ]
}

async def generate_fixtures():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    
    # Ensure provider is set properly
    print("Initializing fixtures generation...")
    
    for role, history in ROLES.items():
        print(f"Generating assessment for {role}...")
        try:
            result = await assessor.assess(
                target_role=role,
                message_history=history,
                language="en",
                interview_meta={"scenario": "Golden Fixture Baseline"}
            )
            
            transcript_path = os.path.join(FIXTURES_DIR, f"{role}_transcript.json")
            with open(transcript_path, "w") as f:
                json.dump(history, f, indent=2)
                
            report_path = os.path.join(FIXTURES_DIR, f"{role}_report.json")
            
            # AssessmentResult is a dataclass
            import dataclasses
            with open(report_path, "w") as f:
                json.dump(dataclasses.asdict(result), f, indent=2, ensure_ascii=False)
                
            print(f"Successfully generated fixtures for {role}")
        except Exception as e:
            print(f"Failed to generate for {role}: {e}", file=sys.stderr)
            
if __name__ == "__main__":
    asyncio.run(generate_fixtures())
