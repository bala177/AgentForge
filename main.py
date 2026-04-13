"""
main.py — Entry point for the AI Agent Platform.

Starts the FastAPI server with uvicorn.

Usage:
  python main.py                  # Start web server (default)
  python main.py --cli            # Interactive CLI mode
  python main.py --host 0.0.0.0   # Custom host
  python main.py --port 8000      # Custom port
"""

import argparse
import sys


def start_server(host: str = "0.0.0.0", port: int = 5000, reload: bool = False):
    """Start the FastAPI server with uvicorn."""
    import uvicorn
    from log_config import get_logger

    # Ensure Unicode box-drawing chars work on Windows (cp1252 terminals/files)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log = get_logger("main")
    log.info("Starting AI Agent Platform on http://%s:%d", host, port)
    print(f"""
    ╔══════════════════════════════════════════════╗
    ║   AI Agent Platform v2.0                     ║
    ║   FastAPI + WebSocket + Multi-Channel        ║
    ║                                              ║
    ║   REST API:    http://{host}:{port}/api       ║
    ║   WebSocket:   ws://{host}:{port}/ws/chat     ║
    ║   Dashboard:   http://{host}:{port}           ║
    ║   API Docs:    http://{host}:{port}/docs      ║
    ╚══════════════════════════════════════════════╝
    """)
    uvicorn.run(
        "gateway.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def start_cli():
    """Run the interactive CLI mode."""
    from runtime.agent import AgentForge
    from llm.provider import LLMProvider

    agent = AgentForge(name="CliBot")

    print(r"""
    +==========================================+
    |   AgentForge — CLI Mode                  |
    |                                          |
    |   24 real tools + Ollama/OpenAI brain    |
    +==========================================+""")

    print("Choose a mode:")
    print("  1. Run demo examples")
    print("  2. Interactive chat")
    print("  3. Both (demo + chat)")
    print("  4. Use Ollama LLM (interactive + AI brain)")
    print()

    choice = input("Enter 1, 2, 3, or 4: ").strip()

    if choice == "4":
        agent.llm_config.provider = "ollama"
        agent.llm = LLMProvider(agent.llm_config)
        ok, msg = agent.llm.is_available()
        print(f"\n  LLM Status: {msg}")
        if ok:
            models = agent.llm.list_models()
            if models:
                print(f"  Models: {', '.join(models)}")
                agent.llm_config.model = models[0]
                print(f"  Using: {models[0]}")
        _interactive_mode(agent)
    elif choice == "1":
        _run_examples(agent)
    elif choice == "2":
        _interactive_mode(agent)
    elif choice == "3":
        _run_examples(agent)
        _interactive_mode(agent)
    else:
        print("Invalid choice. Running demo...")
        _run_examples(agent)


def _run_examples(agent):
    """Run a few example queries."""
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

    agent.show_memory()


def _interactive_mode(agent):
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


def main():
    parser = argparse.ArgumentParser(description="AI Agent Platform")
    parser.add_argument("--cli", action="store_true", help="Run in interactive CLI mode")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Server port (default: 5000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    if args.cli:
        start_cli()
    else:
        start_server(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
