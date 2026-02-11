"""
LangGraph Agent Workflow
Enables multi-step reasoning with tool binding
"""
from typing import List, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, MessagesState, END, START
from langgraph.prebuilt import ToolNode, tools_condition

from .llm import get_llm
from .prompts import RAG_SYSTEM_PROMPT, TOOL_AGENT_PROMPT


class AgentGraph:
    """
    LangGraph-based agent with tool support
    """
    
    def __init__(
        self,
        model_key: str = None,
        tools: List[Any] = None,
        system_prompt: SystemMessage = None
    ):
        self.llm = get_llm(model_key=model_key)
        self.tools = tools or []
        self.system_prompt = system_prompt or RAG_SYSTEM_PROMPT
        
        # Bind tools to LLM if any
        if self.tools:
            self.llm_with_tools = self.llm.bind_tools(tools=self.tools)
        else:
            self.llm_with_tools = self.llm
        
        self.graph = None
    
    def agent_node(self, state: MessagesState):
        """Main agent function - processes messages and generates response"""
        messages = state["messages"]
        
        # Prepend system prompt
        input_messages = [self.system_prompt] + messages
        
        # Generate response
        response = self.llm_with_tools.invoke(input_messages)
        
        return {"messages": [response]}
    
    def build_graph(self) -> StateGraph:
        """Build the LangGraph state graph"""
        graph_builder = StateGraph(MessagesState)
        
        # Add nodes
        graph_builder.add_node("agent", self.agent_node)
        
        if self.tools:
            # Add tool node for tool execution
            graph_builder.add_node("tools", ToolNode(tools=self.tools))
            
            # Add edges with conditional routing
            graph_builder.add_edge(START, "agent")
            graph_builder.add_conditional_edges("agent", tools_condition)
            graph_builder.add_edge("tools", "agent")
        else:
            # Simple flow without tools
            graph_builder.add_edge(START, "agent")
            graph_builder.add_edge("agent", END)
        
        self.graph = graph_builder.compile()
        return self.graph
    
    def invoke(self, question: str, context: str = None) -> str:
        """
        Invoke the agent with a question
        
        Args:
            question: User's question
            context: Optional context from RAG
        
        Returns:
            Agent's response
        """
        if self.graph is None:
            self.build_graph()
        
        # Build input messages
        if context:
            user_message = f"Context:\n{context}\n\nQuestion: {question}"
        else:
            user_message = question
        
        messages = {"messages": [HumanMessage(content=user_message)]}
        
        # Run the graph
        output = self.graph.invoke(messages)
        
        # Extract final response
        if isinstance(output, dict) and "messages" in output:
            return output["messages"][-1].content
        else:
            return str(output)
    
    def get_graph_image(self) -> bytes:
        """Get graph visualization as PNG bytes"""
        if self.graph is None:
            self.build_graph()
        
        return self.graph.get_graph().draw_mermaid_png()
    
    def __call__(self, question: str, context: str = None) -> str:
        """Shorthand for invoke"""
        return self.invoke(question, context)


def create_rag_agent(model_key: str = None) -> AgentGraph:
    """Create a simple RAG agent without tools"""
    return AgentGraph(model_key=model_key)


def create_tool_agent(
    tools: List[Any],
    model_key: str = None
) -> AgentGraph:
    """Create an agent with tool support"""
    return AgentGraph(
        model_key=model_key,
        tools=tools,
        system_prompt=TOOL_AGENT_PROMPT
    )
