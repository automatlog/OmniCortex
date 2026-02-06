"""
Create Complete Agent Test Suite
Generates test files for all agent profiles with their questions
Usage: python scripts/create_agent_test_suite.py
"""
import json
from pathlib import Path
from datetime import datetime

# Output directory
OUTPUT_DIR = Path("tests/agent_test_suite")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Import questions data
try:
    from agent_questions_data import AGENT_QUESTIONS
    print(f"✅ Loaded {len(AGENT_QUESTIONS)} agents from agent_questions_data.py")
except ImportError:
    print("⚠️ agent_questions_data.py not found, using minimal dataset")
    AGENT_QUESTIONS = {}


def parse_agent_questions_from_text(text_file="agent_questions.txt"):
    """
    Parse agent questions from a text file format:
    Agent Name
    1. Question one
    2. Question two
    ...
    """
    agents = {}
    current_agent = None
    current_questions = []
    
    try:
        with open(text_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Check if it's an agent name (no number prefix)
                if not line[0].isdigit() and line.endswith(('.pdf', 'Agent', 'Assistant', 'Consultant', 'Advisor')):
                    # Save previous agent
                    if current_agent and current_questions:
                        agents[current_agent] = current_questions
                    
                    # Start new agent
                    current_agent = line.replace('.pdf', '').replace('_Full_Profile', '').replace('_', ' ').strip()
                    current_questions = []
                
                # Check if it's a question (starts with number)
                elif line[0].isdigit() and '. ' in line:
                    question = line.split('. ', 1)[1]
                    current_questions.append(question)
            
            # Save last agent
            if current_agent and current_questions:
                agents[current_agent] = current_questions
    
    except FileNotFoundError:
        print(f"⚠️ {text_file} not found")
    
    return agents


def generate_test_file(agent_name, questions, output_format="json"):
    """Generate test file for an agent"""
    
    if output_format == "json":
        test_data = {
            "agent_name": agent_name,
            "generated_at": datetime.now().isoformat(),
            "total_questions": len(questions),
            "test_config": {
                "timeout_seconds": 30,
                "expected_response_min_length": 20,
                "retry_on_failure": True
            },
            "questions": [
                {
                    "id": i + 1,
                    "question": q,
                    "expected_response_type": "conversational",
                    "category": categorize_question(q)
                }
                for i, q in enumerate(questions)
            ]
        }
        
        filename = OUTPUT_DIR / f"{sanitize_filename(agent_name)}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, indent=2, ensure_ascii=False)
    
    elif output_format == "txt":
        filename = OUTPUT_DIR / f"{sanitize_filename(agent_name)}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Test Questions for {agent_name}\n")
            f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total Questions: {len(questions)}\n\n")
            for i, q in enumerate(questions, 1):
                f.write(f"{i}. {q}\n")
    
    return filename


def categorize_question(question):
    """Categorize question based on content"""
    q_lower = question.lower()
    
    if any(word in q_lower for word in ['hello', 'hi', 'who is this']):
        return "greeting"
    elif any(word in q_lower for word in ['book', 'appointment', 'schedule']):
        return "booking"
    elif any(word in q_lower for word in ['cost', 'price', 'fee', 'charge']):
        return "pricing"
    elif any(word in q_lower for word in ['help', 'assist', 'support']):
        return "support"
    elif any(word in q_lower for word in ['explain', 'what is', 'can you tell']):
        return "information"
    else:
        return "general"


def sanitize_filename(name):
    """Convert agent name to safe filename"""
    return name.lower().replace(' ', '_').replace('/', '_').replace('\\', '_')


def generate_master_test_runner():
    """Generate a Python script to run all tests"""
    runner_script = OUTPUT_DIR.parent / "run_agent_tests.py"
    
    script_content = '''"""
Run All Agent Tests
Tests all agents with their predefined questions
"""
import json
import requests
from pathlib import Path
from datetime import datetime

API_URL = "http://localhost:8000"
TEST_DIR = Path("tests/agent_test_suite")

def test_agent(agent_name, questions):
    """Test an agent with questions"""
    results = {
        "agent": agent_name,
        "total": len(questions),
        "passed": 0,
        "failed": 0,
        "errors": []
    }
    
    for i, q_data in enumerate(questions, 1):
        question = q_data["question"]
        try:
            response = requests.post(
                f"{API_URL}/query",
                json={"question": question, "agent_id": None},
                timeout=30
            )
            
            if response.status_code == 200:
                answer = response.json().get("answer", "")
                if len(answer) >= 20:  # Minimum response length
                    results["passed"] += 1
                    print(f"  ✅ Q{i}: {question[:50]}...")
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Q{i}: Response too short")
                    print(f"  ❌ Q{i}: Response too short")
            else:
                results["failed"] += 1
                results["errors"].append(f"Q{i}: HTTP {response.status_code}")
                print(f"  ❌ Q{i}: HTTP {response.status_code}")
        
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"Q{i}: {str(e)}")
            print(f"  ❌ Q{i}: {str(e)}")
    
    return results

def main():
    print("🚀 Running Agent Test Suite\\n")
    
    # Find all test files
    test_files = list(TEST_DIR.glob("*.json"))
    print(f"Found {len(test_files)} test files\\n")
    
    all_results = []
    
    for test_file in test_files:
        with open(test_file, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
        
        agent_name = test_data["agent_name"]
        questions = test_data["questions"]
        
        print(f"Testing: {agent_name} ({len(questions)} questions)")
        results = test_agent(agent_name, questions)
        all_results.append(results)
        print(f"  Result: {results['passed']}/{results['total']} passed\\n")
    
    # Summary
    print("="*60)
    print("SUMMARY")
    print("="*60)
    total_passed = sum(r["passed"] for r in all_results)
    total_tests = sum(r["total"] for r in all_results)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_tests - total_passed}")
    print(f"Success Rate: {(total_passed/total_tests*100):.1f}%")

if __name__ == "__main__":
    main()
'''
    
    with open(runner_script, 'w', encoding='utf-8') as f:
        f.write(script_content)
    
    return runner_script


def main():
    print("🚀 Creating Agent Test Suite\n")
    
    # Try to load from data file first
    agents = AGENT_QUESTIONS.copy()
    
    # Try to parse from text file if available
    text_agents = parse_agent_questions_from_text("agent_questions.txt")
    agents.update(text_agents)
    
    if not agents:
        print("❌ No agent data found!")
        print("Please create either:")
        print("  1. agent_questions_data.py with AGENT_QUESTIONS dict")
        print("  2. agent_questions.txt with agent names and questions")
        return
    
    print(f"📊 Generating tests for {len(agents)} agents\n")
    
    # Generate test files
    generated_json = []
    generated_txt = []
    
    for agent_name, questions in agents.items():
        # Generate JSON format
        json_file = generate_test_file(agent_name, questions, "json")
        generated_json.append(json_file)
        
        # Generate TXT format
        txt_file = generate_test_file(agent_name, questions, "txt")
        generated_txt.append(txt_file)
        
        print(f"✅ {agent_name}: {len(questions)} questions")
    
    # Generate master index
    index_data = {
        "generated_at": datetime.now().isoformat(),
        "total_agents": len(agents),
        "total_questions": sum(len(q) for q in agents.values()),
        "agents": [
            {
                "name": name,
                "question_count": len(questions),
                "test_file_json": f"{sanitize_filename(name)}.json",
                "test_file_txt": f"{sanitize_filename(name)}.txt"
            }
            for name, questions in agents.items()
        ]
    }
    
    index_file = OUTPUT_DIR / "index.json"
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2)
    
    # Generate test runner
    runner_file = generate_master_test_runner()
    
    print(f"\n{'='*60}")
    print("✅ Test Suite Generated!")
    print(f"{'='*60}")
    print(f"📁 Output directory: {OUTPUT_DIR}")
    print(f"📋 JSON files: {len(generated_json)}")
    print(f"📄 TXT files: {len(generated_txt)}")
    print(f"📊 Total questions: {sum(len(q) for q in agents.values())}")
    print(f"🏃 Test runner: {runner_file}")
    print(f"\nRun tests with: python {runner_file}")


if __name__ == "__main__":
    main()
