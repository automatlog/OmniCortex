"""
Generate Test Files for All Agent Profiles
Creates JSON test files with predefined questions for each agent type
Usage: python scripts/generate_agent_tests.py
"""
import json
from pathlib import Path
from datetime import datetime


# Output directory
OUTPUT_DIR = Path("tests/agent_questions")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Complete agent test data with all questions from your list
AGENT_TESTS = {
    "AI_Agent_Configurator": [
        "Hi, I want to create a new AI agent.",
        "What details do you need from me?",
        "What is an agent persona?",
        "Can you help me define the agent's role?",
        "What tasks can this agent handle?",
        "How do I write a system prompt?",
        "Can I change the agent later?",
        "How do I connect data or documents?",
        "Can this agent talk to users directly?",
        "How do I test if the agent works properly?",
        "Can I save and reuse this agent?",
        "Is this agent ready to deploy?"
    ],
    "Automotive_Mobility_Agent": [
        "Hello, I need help with a vehicle service.",
        "Can you explain my car issue?",
        "What could be the reason for this problem?",
        "Is it safe to drive right now?",
        "How much will the repair cost?",
        "How long will the service take?",
        "Can you help me book a service appointment?",
        "Do I need to replace any parts?",
        "Is this covered under warranty?",
        "Can you suggest regular maintenance tips?"
    ],
    "Bank_Service_Assistant": [
        "Hi, I need help with my bank account.",
        "Can you check my account details?",
        "Why was this amount deducted?",
        "Can you explain this bank charge?",
        "How can I check my balance?",
        "What is my last transaction?",
        "How do I apply for a debit or credit card?",
        "My transaction failed, what should I do?",
        "Can you help me raise a complaint?",
        "How long will the issue take to resolve?",
        "Is my account secure?"
    ],
    "Business_Analytics_Reporter": [
        "Hello, I want to see my business data.",
        "Can you explain this report in simple words?",
        "What do these numbers mean?",
        "Are my sales increasing or decreasing?",
        "Which product is performing best?",
        "Where am I losing money?",
        "Can you show monthly comparison?",
        "What are my key metrics?",
        "Can you generate a summary report?",
        "What actions should I take based on this data?"
    ],
    "CRM_Solution_Architect": [
        "Hello, I want to set up a CRM system.",
        "What is a CRM and why do I need it?",
        "Which CRM is best for my business?",
        "Can you help me design the CRM flow?",
        "How will customer data be stored?",
        "Can this CRM track leads and sales?",
        "How will my team use this CRM daily?",
        "Can CRM send follow-up reminders?",
        "Can it integrate with email or WhatsApp?",
        "Is customer data secure here?",
        "Can this CRM grow as my business grows?",
        "How do I get started with implementation?"
    ],
    "Career_Counselor": [
        "Hello, who is this?",
        "I need help with my career.",
        "What careers match my interests?",
        "What skills do I need for this career?",
        "Which course should I choose?",
        "Is this career good for the future?",
        "What qualifications are required?",
        "Can you suggest career options after my studies?",
        "How much salary can I expect?",
        "What are the growth opportunities?",
        "Can you help me make a career plan?",
        "What should be my next step?"
    ],
    "Clinic_Reception": [
        "Hello, who is this?",
        "I want to book a doctor appointment.",
        "Which doctors are available today?",
        "What are the consultation timings?",
        "Can you book an appointment for me?",
        "What details do you need from me?",
        "Is this appointment online or offline?",
        "How much is the consultation fee?",
        "Can I reschedule my appointment?",
        "What if I want to cancel the booking?",
        "Will I get a confirmation message?",
        "Where is the clinic located?"
    ],
    "Coding_Bootcamp_Mentor": [
        "Hello, who is this?",
        "I want to learn coding.",
        "Which programming language should I start with?",
        "Is this course good for beginners?",
        "How long will it take to learn basics?",
        "Do I need any prior knowledge?",
        "What topics will be covered in this bootcamp?",
        "Will I get hands-on practice?",
        "Can you help me with doubts while learning?",
        "Will this help me get a job?",
        "Do you provide projects or assignments?",
        "What should I do after completing the course?"
    ],
    "Competitive_Exam_Coach": [
        "Hello, who is this?",
        "I am preparing for a competitive exam.",
        "Which exam do you help with?",
        "Can you help me make a study plan?",
        "How many hours should I study daily?",
        "What syllabus should I focus on first?",
        "Can you explain topics in simple way?",
        "Do you provide practice questions?",
        "How can I improve my weak subjects?",
        "Can you help with time management?",
        "How should I revise before the exam?",
        "Any tips to reduce exam stress?"
    ],
    "Complaint_Resolution_Agent": [
        "Hello, who is this?",
        "I want to raise a complaint.",
        "Can you tell me what details you need?",
        "Where can I explain my issue?",
        "Can you check the status of my complaint?",
        "How long will it take to resolve?",
        "Who is handling my complaint?",
        "Can you escalate this issue?",
        "Will I get updates on my complaint?",
        "What if I am not satisfied with the solution?",
        "Can I reopen the complaint?",
        "What is the final resolution step?"
    ]
}


def generate_test_file(agent_name, questions):
    """Generate a test file for an agent"""
    test_data = {
        "agent_name": agent_name,
        "generated_at": datetime.now().isoformat(),
        "total_questions": len(questions),
        "questions": [
            {
                "id": i + 1,
                "question": q,
                "expected_response_type": "conversational",
                "category": "general"
            }
            for i, q in enumerate(questions)
        ]
    }
    
    # Save to file
    filename = OUTPUT_DIR / f"{agent_name.lower()}_test.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)
    
    return filename


def generate_all_tests():
    """Generate test files for all agents"""
    print(f"🚀 Generating test files for {len(AGENT_TESTS)} agents...")
    print(f"📁 Output directory: {OUTPUT_DIR}\n")
    
    generated = []
    for agent_name, questions in AGENT_TESTS.items():
        filename = generate_test_file(agent_name, questions)
        print(f"✅ {agent_name}: {len(questions)} questions → {filename.name}")
        generated.append(filename)
    
    # Generate master index
    index_data = {
        "generated_at": datetime.now().isoformat(),
        "total_agents": len(AGENT_TESTS),
        "total_questions": sum(len(q) for q in AGENT_TESTS.values()),
        "agents": [
            {
                "name": name,
                "question_count": len(questions),
                "test_file": f"{name.lower()}_test.json"
            }
            for name, questions in AGENT_TESTS.items()
        ]
    }
    
    index_file = OUTPUT_DIR / "index.json"
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2)
    
    print(f"\n📋 Master index: {index_file.name}")
    print(f"\n✅ Generated {len(generated)} test files")
    print(f"📊 Total questions: {sum(len(q) for q in AGENT_TESTS.values())}")


if __name__ == "__main__":
    generate_all_tests()
