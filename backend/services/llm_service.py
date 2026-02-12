# backend/services/llm_service.py - WITH FIXED FALLBACK CITATIONS

from typing import List, Dict, Optional
from openai import AzureOpenAI
import uuid
import re
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
    
    def _build_system_prompt(self, has_uploads: bool = False) -> str:
        base_prompt = """You are an AI assistant for YottaReal property management software, helping leasing agents, property managers, and district managers retrieve information.

Your role:
- Answer questions based ONLY on the provided context from documents
- Be thorough and detailed in your responses
- If information is not in the provided context, clearly state that you don't have that information
- Focus on practical, actionable information

FORMATTING REQUIREMENTS (CRITICAL):
- Do NOT use ** for bold text or any Markdown formatting
- DO use bullet points with this EXACT format:
  
  Main topic:
  - Bullet point 1 with details
  - Bullet point 2 with details
  - Bullet point 3 with details

- Each bullet point should be on its OWN line or paragraph for clarity.
- Use dashes (-) for bullet points

CRITICAL CITATION REQUIREMENT WITH PAGE NUMBERS:
When you reference information from a document, you MUST cite it using this format:
[N → Page X] where N is the document number and X is the actual page number from the PDF

Example: "According to the Move-Out Policy [1 → Page 3], residents must provide 60 days notice."

Guidelines:
- Prioritize accuracy and completeness
- Use bullet points on separate lines for easy reading
- Include relevant policy numbers or section references when available
- Provide detailed explanations with context
- For ambiguous queries, ask clarifying questions
- Always ground your answers in the provided documents
- ALWAYS include [N → Page X] citations when referencing specific information
- Make responses thorough and informative"""

        if has_uploads:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing UPLOADED documents, say "According to your uploaded document [N → Page X]..." or "In [document name] [N → Page X]..."
- When referencing COMPANY or BLOB STORAGE documents (policies, handbooks), say "According to [policy/handbook name] [N → Page X]..." or "Company policy [N → Page X] states..."
- Be clear about which source each piece of information comes from
- If there are multiple uploaded documents and the query is ambiguous, describe ALL of them with their [N → Page X] citations
- Provide comprehensive details from the uploaded documents in bullet format"""
        else:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing information, naturally mention the source with [N → Page X] citation (e.g., "According to the Move-Out Policy [1 → Page 3]..." or "As stated in the Team Member Handbook [2 → Page 15]...")
- Provide comprehensive information from the cited documents in bullet format"""

        return base_prompt
    
    def _build_prompt(self, query: str, context: List[Dict], has_uploads: bool = False) -> tuple:
        # Separate uploaded vs company documents
        uploaded_docs = [doc for doc in context if doc.get("source_type") == "uploaded"]
        company_docs = [doc for doc in context if doc.get("source_type") == "company"]
        
        context_text = ""
        doc_number = 1
        doc_mapping = {}  # Maps doc number to filename, download_url, pages
        
        # Add uploaded documents first (higher priority)
        if uploaded_docs:
            context_text += "=== UPLOADED DOCUMENTS (User's Files) ===\n"
            for doc in uploaded_docs:
                page_num = doc.get('page_number', 1)
                
                context_text += f"\n[Document {doc_number} - Page {page_num}: {doc['filename']}]\n"
                
                # Track this doc
                if doc_number not in doc_mapping:
                    doc_mapping[doc_number] = {
                        "filename": doc['filename'],
                        "type": "uploaded",
                        "download_url": doc.get('download_url'),
                        "pages": set()
                    }
                doc_mapping[doc_number]["pages"].add(page_num)
                
                context_text += f"{doc['content']}\n"
                context_text += f"(End of Document {doc_number} - Page {page_num})\n"
                doc_number += 1
        
        # Add company documents
        if company_docs:
            if uploaded_docs:
                context_text += "\n" + "="*60 + "\n\n"
            context_text += "=== COMPANY DOCUMENTS (Policies, Handbooks, Procedures) ===\n"
            for doc in company_docs:
                page_num = doc.get('page_number', 1)
                
                context_text += f"\n[Document {doc_number} - Page {page_num}: {doc['filename']}]\n"
                
                # Track this doc
                if doc_number not in doc_mapping:
                    doc_mapping[doc_number] = {
                        "filename": doc['filename'],
                        "type": "company",
                        "download_url": doc.get('download_url'),
                        "pages": set()
                    }
                doc_mapping[doc_number]["pages"].add(page_num)
                
                # Allow up to 10,000 chars per company doc
                content = doc['content'][:10000]
                context_text += f"{content}\n"
                if len(doc['content']) > 10000:
                    context_text += f"... (content truncated, original length: {len(doc['content'])} chars)\n"
                context_text += f"(End of Document {doc_number} - Page {page_num})\n"
                doc_number += 1
        
        prompt = f"""Context from documents:

{context_text}

User question: {query}

Answer (use bullet points on separate lines with [N → Page X] citations):"""
        
        return prompt, doc_mapping
    
    def _extract_citations_and_renumber(self, response_text: str, doc_mapping: Dict) -> tuple:
        """
        Extract citations, deduplicate by filename, renumber sequentially, 
        and update response text with new numbers
        """
        # Find all [N → Page X] or [N] patterns
        citation_pattern = r'\[(\d+)(?:\s*→\s*Page\s*(\d+))?\]'
        matches = re.finditer(citation_pattern, response_text)
        
        # Track which doc numbers were cited
        cited_docs = {}  # {doc_num: page_nums}
        for match in matches:
            doc_num = int(match.group(1))
            page_num = match.group(2)
            if doc_num not in cited_docs:
                cited_docs[doc_num] = set()
            if page_num:
                cited_docs[doc_num].add(int(page_num))
        
        # Build unique sources (deduplicate by filename)
        unique_sources = {}  # {filename: {"new_num": int, "type": str, "url": str, "old_nums": [int]}}
        new_num = 1
        
        for doc_num in sorted(cited_docs.keys()):
            if doc_num in doc_mapping:
                doc_info = doc_mapping[doc_num]
                filename = doc_info['filename']
                
                # Check if we've already seen this filename
                if filename not in unique_sources:
                    unique_sources[filename] = {
                        "new_num": new_num,
                        "type": doc_info["type"],
                        "download_url": doc_info.get("download_url"),
                        "old_nums": []
                    }
                    new_num += 1
                
                unique_sources[filename]["old_nums"].append(doc_num)
        
        # Create renumbering map: old doc num → new sequential num
        renumber_map = {}  # {old_num: new_num}
        for filename, info in unique_sources.items():
            for old_num in info["old_nums"]:
                renumber_map[old_num] = info["new_num"]
        
        # Replace citation numbers in response text
        def replace_citation(match):
            old_num = int(match.group(1))
            page_num = match.group(2)
            
            if old_num in renumber_map:
                new_num = renumber_map[old_num]
                if page_num:
                    return f"[{new_num} → Page {page_num}]"
                else:
                    return f"[{new_num}]"
            return match.group(0)  # Keep original if not in map
        
        updated_text = re.sub(citation_pattern, replace_citation, response_text)
        
        # Build sources list with sequential numbers
        sources = []
        for filename, info in sorted(unique_sources.items(), key=lambda x: x[1]["new_num"]):
            icon = "📤" if info["type"] == "uploaded" else "📁"
            sources.append({
                "filename": f"{icon} {filename}",
                "type": info["type"],
                "download_url": info.get("download_url"),
                "citation_number": info["new_num"]
            })
        
        return updated_text, sources
    
    def _clean_response(self, response_text: str) -> str:
        """Remove unnecessary markdown (keep [N → Page X] citations)"""
        # Just clean up any ** markdown
        cleaned = re.sub(r'\*\*', '', response_text)
        return cleaned.strip()
    
    async def generate_response(
        self, 
        query: str, 
        context: List[Dict],
        session_id: Optional[str] = None,
        has_uploads: bool = False,
        is_comparison: bool = False
    ) -> Dict:
        if not session_id:
            session_id = str(uuid.uuid4())
        
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        
        system_prompt = self._build_system_prompt(has_uploads)
        user_prompt, doc_mapping = self._build_prompt(query, context, has_uploads)
        
        # Calculate actual prompt size
        total_chars = len(user_prompt)
        estimated_tokens = total_chars // 4
        
        uploaded_chars = sum(len(doc['content']) for doc in context if doc.get('source_type') == 'uploaded')
        company_chars = sum(min(len(doc['content']), 10000) for doc in context if doc.get('source_type') == 'company')
        
        print(f"📊 Prompt Statistics:")
        print(f"   Total prompt: {total_chars:,} chars (~{estimated_tokens:,} tokens)")
        print(f"   Uploaded content: {uploaded_chars:,} chars (FULL, no truncation)")
        print(f"   Company content: {company_chars:,} chars")
        print(f"   Context window available: ~128,000 tokens")
        print(f"   Usage: {(estimated_tokens/128000)*100:.1f}%")
        print(f"   Documents provided: {len(doc_mapping)}")
        
        try:
            response = await self._generate_azure_openai(
                system_prompt, 
                user_prompt, 
                session_id
            )
            
            # Extract citations, deduplicate, renumber, and update text
            cleaned_response = self._clean_response(response)
            updated_response, sources = self._extract_citations_and_renumber(cleaned_response, doc_mapping)
            
            print(f"✅ Generated response with inline citations")
            print(f"   Documents provided: {len(doc_mapping)}")
            print(f"   Unique documents cited: {len(sources)}")
            if sources:
                for src in sources:
                    print(f"     [{src['citation_number']}] {src['filename']}")
            else:
                print(f"   ⚠️  No documents cited")
            
            # Store conversation
            self.conversation_history[session_id].append({
                "query": query,
                "response": updated_response
            })
            
            # If no citations found, fall back to showing all docs (WITH CITATION NUMBERS)
            if not sources and context:
                # Only show fallback if there are enough docs (likely a real query)
                if len(context) >= 5:
                    print(f"   ⚠️  Falling back to showing all provided documents")
                    sources = []
                    seen_files = set()
                    citation_num = 1  # Start citation numbering
                    
                    for doc in context:
                        filename = doc["filename"]
                        if filename not in seen_files:
                            seen_files.add(filename)
                            doc_type = doc.get("source_type", "unknown")
                            icon = "📤" if doc_type == "uploaded" else "📁"
                            sources.append({
                                "filename": f"{icon} {filename}",
                                "type": doc_type,
                                "download_url": doc.get("download_url"),
                                "citation_number": citation_num  # Add citation number
                            })
                            citation_num += 1
                else:
                    # Likely casual chat that slipped through - don't show sources
                    print(f"   ℹ️  No citations and few docs - likely casual chat, not showing sources")
            
            return {
                "answer": updated_response,
                "sources": sources,
                "session_id": session_id
            }
        
        except Exception as e:
            print(f"❌ LLM generation error: {e}")
            import traceback
            traceback.print_exc()
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
        
        # Add ALL conversation history
        for msg in self.conversation_history[session_id]:
            messages.append({"role": "user", "content": msg["query"]})
            messages.append({"role": "assistant", "content": msg["response"]})
        
        # Add current message
        messages.append({"role": "user", "content": user_prompt})
        
        # Log conversation length for monitoring
        total_history_messages = len(self.conversation_history[session_id])
        print(f"📝 Including {total_history_messages} previous exchanges in context")
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=2500
        )
        
        return response.choices[0].message.content