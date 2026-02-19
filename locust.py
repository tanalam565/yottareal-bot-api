from locust import HttpUser, task, between
import random

class ChatbotUser(HttpUser):
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Called when a user starts"""
        self.session_id = f"load-test-{random.randint(1000, 9999)}"
        self.api_key = "test-key-12345"  # ← CHANGE THIS
    
    @task(3)  # Weight 3 - happens 3x more than upload
    def send_chat_message(self):
        """Simulate a chat message"""
        queries = [
            "What are the move-out procedures?",
            "Tell me about the security deposit policy",
            "What is the pet policy?",
            "How do I submit a maintenance request?",
            "What are the lease renewal terms?",
        ]
        
        
        self.client.post(
            "/api/chat",
            json={
                "message": random.choice(queries),
                "session_id": self.session_id
            },
            headers={"X-API-Key": self.api_key}
        )
    
    @task(1)  # Weight 1 - happens less frequently
    def check_health(self):
        """Health check"""
        self.client.get("/api/health")