"""
Quick start script for AI Desktop Copilot.
Run this to start the application.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.main import run_server

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="AI Desktop Copilot")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--dev", action="store_true", help="Development mode")
    
    args = parser.parse_args()
    
    # Set environment
    if args.dev:
        os.environ["DEBUG"] = "true"
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🤖 AI Desktop Copilot v1.0.0                              ║
║                                                              ║
║   Starting server on {args.host}:{args.port}                        ║
║   API Documentation: http://{args.host}:{args.port}/docs            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    run_server(host=args.host, port=args.port, reload=args.reload)
