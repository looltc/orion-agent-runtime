from orion_agent_runtime.main import greet

def test_greet():
    assert greet("Tester") == "Hello, Tester! Welcome to Orion agent runtime."
