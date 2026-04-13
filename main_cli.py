"""
main.py — Run the AgentForge AI Agent.

This file demonstrates the agent in action with example queries,
then drops into an interactive chat mode.
"""

from agent import AgentForge


def run_examples(agent: AgentForge):
    """Run a few example queries to show how the agent works."""

    examples = [
        "What is the weather in Tokyo?",
        "Calculate factorial(10) / 1000",
        "What date and time is it?",
        "Convert 100 F to C",
        "Who is Alan Turing?",
        "Search for Python programming tutorials",
        "What's my IP address?",
        "Save a note: buy groceries tomorrow",
    ]

    print("\n" + "=" * 60)
    print("  DEMO: Running example queries")
    print("=" * 60)

    for query in examples:
        result = agent.run(query)
        print(f"  Mode: {result.get('mode', 'unknown')}")
        if result.get('model'):
            print(f"  Model: {result['model']}")

    # Show what the agent remembers
    agent.show_memory()


def interactive_mode(agent: AgentForge):
    """Chat with the agent interactively."""

    print("\n" + "=" * 60)
    print("  INTERACTIVE MODE")
    print("  Type a question or command. Type 'quit' to exit.")
    print("  Type 'tools' to see available tools.")
    print("  Type 'memory' to see the agent's memory.")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if user_input.lower() == "tools":
            print(agent.available_tools_summary())
            continue
        if user_input.lower() == "memory":
            agent.show_memory()
            continue

        result = agent.run(user_input)
        if result.get('mode') == 'llm':
            print(f"\n  [{result.get('model', 'LLM')}] {result['answer']}")
        # Console output is handled by agent.run() print statements


def main():
    # Create the agent
    agent = AgentForge(name="ForgeBot")

    print(r"""
    +==========================================+
    |   AgentForge — LLM-Powered Agent         |
    |                                          |
    |   13 real tools + Ollama/OpenAI brain    |
    |     * Real weather (any city)            |
    |     * Web search (DuckDuckGo)            |
    |     * Wikipedia lookup                   |
    |     * Web page fetcher                   |
    |     * File manager                       |
    |     * System info                        |
    |     * Text analyzer                      |
    |     * Hash & encode                      |
    |     * IP & network lookup                |
    |     * Calculator (full math)             |
    |     * Unit converter (80+ pairs)         |
    |     * Date/time with timezones           |
    |     * Persistent notes                   |
    +==========================================+
    """)

    print("Choose a mode:")
    print("  1. Run demo examples (see the agent in action)")
    print("  2. Interactive chat (talk to the agent)")
    print("  3. Both (demo first, then chat)")
    print("  4. Use Ollama LLM (interactive + AI brain)")
    print()

    choice = input("Enter 1, 2, 3, or 4: ").strip()

    if choice == "4":
        agent.llm_config.provider = "ollama"
        from llm_provider import LLMProvider
        agent.llm = LLMProvider(agent.llm_config)
        ok, msg = agent.llm.is_available()
        print(f"\n  LLM Status: {msg}")
        if ok:
            models = agent.llm.list_models()
            if models:
                print(f"  Models: {', '.join(models)}")
                agent.llm_config.model = models[0]
                print(f"  Using: {models[0]}")
        interactive_mode(agent)
    elif choice == "1":
        run_examples(agent)
    elif choice == "2":
        interactive_mode(agent)
    elif choice == "3":
        run_examples(agent)
        interactive_mode(agent)
    else:
        print("Invalid choice. Running demo...")
        run_examples(agent)


if __name__ == "__main__":
    main()
