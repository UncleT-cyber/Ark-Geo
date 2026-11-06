import re

# Global AgentManager instance for local command routing
_agent_manager = None

class AgentManager:
    def __init__(self):
        # Local state inventory of registered ARK/CAI agents
        self.agents_roster = {
            "operator": {
                "description": "Primary orchestration agent handling user sessions and intent routing.",
                "status": "Active"
            },
            "red_team": {
                "description": "Offensive security agent handling automated pen-testing, Nmap scanning, and exploits.",
                "status": "Available"
            },
            "blue_team": {
                "description": "Defensive mitigation agent handling threat detection and system hardening.",
                "status": "Available"
            }
        }

    def process_input(self, user_input: str) -> str | None:
        """
        Evaluates input. Returns a string response if it is a local command.
        Returns None if the input should be forwarded to the Autonomous ReAct LLM.
        """
        # Normalize: strip spaces, lower case, remove leading slashes
        normalized = user_input.strip().lower().lstrip('/')
        
        # Normalize common typos to match standard routing ('agants' -> 'agent')
        normalized = re.sub(r'\bagants\b', 'agent', normalized)
        
        # Tokenize input
        tokens = normalized.split()
        if not tokens:
            return None
            
        # Target matching: checking for agent/agents base keywords
        if tokens[0] in ["agent", "agents"]:
            if len(tokens) > 1 and tokens[1] in ["list", "lists"]:
                return self.generate_roster_output()
            else:
                return "● ARK — Usage: /agent list"
                
        return None

    def generate_roster_output(self) -> str:
        border = "=" * 65
        output = [
            "● ARK — CAI UNIFIED ENGINE: Multi-Agent Inventory",
            border
        ]
        for name, data in self.agents_roster.items():
            status_tag = f"[{data['status']}]"
            output.append(f"• {status_tag:<11} {name:<12} - {data['description']}")
        return "\n".join(output)

# Global function to access the agent manager
def get_agent_manager() -> AgentManager:
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
    return _agent_manager

# Process input using the global agent manager
def process_input(user_input: str) -> str | None:
    return get_agent_manager().process_input(user_input)