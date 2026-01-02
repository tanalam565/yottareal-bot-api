from typing import List, Dict, Optional
from openai import AzureOpenAI
import uuid
import config

class LLMService:
    def __init__(self):
        self.conversation_history = {}
        
        self.client = AzureOpenAI(
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT
        )
        self.model = config.AZURE_OPENAI_DEPLOYMENT_NAME
    
    def _build_system_prompt(self) -> str:
        return """You are an AI assistant for Yottareal property management software, helping leasing office employees and property managers retrieve information from company documents.

Your role:
- Answer questions based ONLY on the provided context from property management documents
- Be concise and professional
- When referencing information from a document, naturally mention the source (e.g., "According to the Move-Out Policy..." or "As stated in the Team Member Handbook...")
- If information is not in the provided context, clearly state that you don't have that information
- Focus on practical, actionable information

Guidelines:
- Prioritize accuracy over completeness
- Use bullet points for procedures or lists when appropriate
- Include relevant policy numbers or section references when available
- For ambiguous queries, ask clarifying questions
- Always ground your answers in the provided documents"""
    
    def _build_prompt(self, query: str, context: List[Dict]) -> str:
        context_text = "\n\n".join([
            f"[Source: {doc['filename']}]\n{doc['content']}"
            for doc in context
        ])
        
        prompt = f"""Based on the following context from property management documents, answer the user's question.

Context:
{context_text}

Question: {query}

Answer:"""
        return prompt
    
    async def generate_response(
        self, 
        query: str, 
        context: List[Dict],
        session_id: Optional[str] = None
    ) -> Dict:
        if not session_id:
            session_id = str(uuid.uuid4())
        
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_prompt(query, context)
        
        try:
            response = await self._generate_azure_openai(
                system_prompt, 
                user_prompt, 
                session_id
            )
            
            # Store conversation
            self.conversation_history[session_id].append({
                "query": query,
                "response": response
            })
            
            # Extract and deduplicate source documents
            seen_files = set()
            unique_sources = []
            
            for doc in context:
                filename = doc["filename"]
                if filename not in seen_files:
                    seen_files.add(filename)
                    unique_sources.append({
                        "filename": filename,
                        "score": doc.get("score", 0)
                    })
            
            # Sort by relevance score (highest first)
            unique_sources.sort(key=lambda x: x["score"], reverse=True)
            
            return {
                "answer": response,
                "sources": unique_sources,
                "session_id": session_id
            }
        
        except Exception as e:
            print(f"LLM generation error: {e}")
            return {
                "answer": "I apologize, but I encountered an error processing your request.",
                "sources": [],
                "session_id": session_id
            }
    
    async def _generate_azure_openai(
        self, 
        system_prompt: str, 
        user_prompt: str,
        session_id: str
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        for msg in self.conversation_history[session_id][-3:]:
            messages.append({"role": "user", "content": msg["query"]})
            messages.append({"role": "assistant", "content": msg["response"]})
        
        messages.append({"role": "user", "content": user_prompt})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=1000
        )
        
        return response.choices[0].message.content