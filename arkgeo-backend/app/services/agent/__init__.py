"""ARK native tool-calling agent — JSON Function Schemas + ReAct loop.

``tools.py`` derives OpenAI-format JSON Function Schemas from the ARK Tool
Registry and executes model-proposed calls through it; ``loop.py`` runs the
iterative tool-calling ReAct loop on top. Everything is derived at runtime —
adding a tool to the registry automatically adds its function schema, so the
framework stays tool-agnostic for future capabilities.
"""
