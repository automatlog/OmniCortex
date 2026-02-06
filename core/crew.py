"""
CrewAI Integration - Multi-Agent Orchestration
"""
from crewai import Agent, Task, Crew, Process
from .llm import get_llm
from .monitoring import ACTIVE_AGENTS

class CrewManager:
    """
    Manages dynamic creation of crews for complex tasks
    """
    
    @staticmethod
    def create_research_crew(topic: str, agent_goal: str = "Provide detailed analysis"):
        """
        Creates a simple Research & Write crew
        """
        llm = get_llm()
        
        # 1. Researcher Agent
        researcher = Agent(
            role='Senior Research Analyst',
            goal=f'Uncover cutting-edge developments in {topic}',
            backstory="""You are an expert at analyzing data and documents. 
            You have a knack for finding hidden details.""",
            verbose=True,
            allow_delegation=False,
            llm=llm
        )
        
        # 2. Writer Agent
        writer = Agent(
            role='Tech Content Strategist',
            goal='Craft compelling content on tech advancements',
            backstory="""You are a renowned Content Strategist, known for 
            simplifying complex topics into engaging narratives.""",
            verbose=True,
            allow_delegation=True,
            llm=llm
        )
        
        # Define Tasks
        task1 = Task(
            description=f"""Conduct a comprehensive analysis of {topic}.
            Identify key trends, potential challenges, and future implications.""",
            expected_output="Full analysis report in bullet points",
            agent=researcher
        )
        
        task2 = Task(
            description=f"""Using the insights provided, write an engaging blog post about {topic}.
            Your post should be informative yet accessible to a general audience.
            Avoid complex jargon.""",
            expected_output="A 3 paragraph blog post in markdown",
            agent=writer
        )
        
        # Create Crew
        crew = Crew(
            agents=[researcher, writer],
            tasks=[task1, task2],
            verbose=True,
            process=Process.sequential
        )
        
        return crew

    @staticmethod
    def run_crew(topic: str):
        """Run the research crew"""
        ACTIVE_AGENTS.inc(2) # Tracking active agents
        try:
            crew = CrewManager.create_research_crew(topic)
            result = crew.kickoff()
            return result
        finally:
            ACTIVE_AGENTS.dec(2)
