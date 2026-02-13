/**
 * ChatInterface Component
 * 
 * A comprehensive chat interface component that allows users to:
 * - Upload documents (PDF, images, DOCX, TXT, etc.)
 * - Send messages to an AI assistant
 * - View responses with inline citations referencing source documents
 * - Download source documents
 * - Manage uploaded files
 * 
 * The component uses session-based tracking to associate uploads with chat sessions,
 * and includes automatic cleanup of sessions when the user leaves.
 */

import React, { useState, useRef, useEffect } from 'react';
import { sendMessage } from '../services/api';
import './ChatInterface.css';

// ============ Configuration & Constants ============

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';
const API_KEY = process.env.REACT_APP_CHATBOT_API_KEY || '';
const SUPPORTED_FORMATS = '.pdf,.jpg,.jpeg,.png,.tiff,.bmp,.docx,.txt';
const COPY_FEEDBACK_DURATION = 2000;
const CITE_HIGHLIGHT_DURATION = 1000;
const REQUEST_TIMEOUT = 30000;

if (!API_BASE_URL) {
  console.error('CRITICAL: REACT_APP_API_URL environment variable is not set');
}

/**
 * ChatInterface - Main chat interface component
 * 
 * @component
 * @returns {React.ReactElement} The rendered chat interface with upload, messages, and input sections
 */
function ChatInterface() {
  // ============ State Management ============
  
  /** @type {[Array<Object>, Function]} Array of chat messages with role, content, sources, and timestamp */
  const [messages, setMessages] = useState([]);
  
  /** @type {[string, Function]} Current user input text in the message field */
  const [input, setInput] = useState('');
  
  /** @type {[boolean, Function]} Loading state indicating if a message is being sent/received */
  const [loading, setLoading] = useState(false);
  
  /** @type {[string, Function]} Unique session identifier for grouping uploads and chat history */
  const [sessionId, setSessionId] = useState(() => {
    return `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  });
  
  /** @type {[number|null, Function]} Index of the message that was recently copied to clipboard */
  const [copiedIndex, setCopiedIndex] = useState(null);
  
  /** @type {[boolean, Function]} Loading state indicating if files are being uploaded */
  const [uploading, setUploading] = useState(false);
  
  /** @type {[Array<Object>, Function]} Array of successfully uploaded files with metadata */
  const [uploadedFiles, setUploadedFiles] = useState([]);
  
  // ============ Ref Management ============
  
  /** @type {React.MutableRefObject} Reference to the end of messages container for auto-scrolling */
  const messagesEndRef = useRef(null);
  
  /** @type {React.MutableRefObject} Reference to the hidden file input element */
  const fileInputRef = useRef(null);
  
  /** @type {React.MutableRefObject} Map of citation references for scroll-to-citation functionality */
  const citationsRef = useRef({});

  // ============ Effect Hooks ============
  
  /**
   * Log session ID only in development mode
   */
  useEffect(() => {
    if (process.env.NODE_ENV === 'development') {
      console.log('🔑 Session ID:', sessionId);
    }
  }, [sessionId]);

  // ============ Helper Functions ============
  
  /**
   * Smoothly scrolls the chat container to show the latest message
   * Called automatically when new messages arrive
   */
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  /**
   * Auto-scroll to bottom when messages change
   */
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  /**
   * Cleanup effect: Deletes uploaded files and session data when component unmounts
   * or when user navigates away from the page.
   * This prevents orphaned files left on the server.
   */
  useEffect(() => {
    const cleanupSession = async () => {
      if (uploadedFiles.length > 0 && sessionId) {
        if (process.env.NODE_ENV === 'development') {
          console.log('🗑️ Cleaning up session on unmount:', sessionId);
        }
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
          
          await fetch(
            `${API_BASE_URL}/cleanup-session`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-API-Key': API_KEY
              },
              body: JSON.stringify({ session_id: sessionId }),
              keepalive: true,
              signal: controller.signal
            }
          );
          clearTimeout(timeoutId);
        } catch (error) {
          if (error.name !== 'AbortError' && process.env.NODE_ENV === 'development') {
            console.error('Cleanup error:', error);
          }
        }
      }
    };

    const handleBeforeUnload = () => {
      if (uploadedFiles.length > 0) {
        cleanupSession();
      }
    };

    // Register cleanup on page unload
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      cleanupSession();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Copies message text to clipboard, removing inline citation markers
   * Shows visual feedback (✓ Copied) for 2 seconds
   * 
   * @param {string} text - The full message text including citations
   * @param {number} index - The index of the message in the messages array
   */
  const handleCopy = (text, index) => {
    // Remove inline citation markers like [1 → Page 4] before copying
    const cleanText = text.replace(/\[(\d+)\s*→\s*Page\s*\d+\]/g, '');
    
    navigator.clipboard.writeText(cleanText).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), COPY_FEEDBACK_DURATION);
    }).catch(() => {
      // Silently fail - user can try again
    });
  };

  /**
   * Downloads a source document by initiating a browser download
   * Called when user double-clicks a citation source
   * 
   * @param {Object} source - The source object containing download_url and filename
   * @param {string} source.download_url - URL to download the file from
   * @param {string} source.filename - Display name of the file
   */
  const handleCitationDownload = (source) => {
    if (!source?.download_url) {
      return;
    }

    try {
      const link = document.createElement('a');
      link.href = source.download_url;
      link.download = source.filename.replace(/^[📁📤]\s*/, '').split('→')[0].trim();
      link.target = '_blank';
      
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (error) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Download error:', error);
      }
    }
  };

  /**
   * Scrolls to and highlights a citation source in the sources list
   * Called when user clicks an inline citation marker in the message text
   * 
   * @param {number} citationNumber - The citation number (e.g., 1, 2, 3)
   * @param {number} messageIndex - The index of the message containing the citation
   */
  const scrollToCitation = (citationNumber, messageIndex) => {
    const citationElement = citationsRef.current[`${messageIndex}-${citationNumber}`];
    if (citationElement) {
      // Scroll to the citation with smooth behavior
      citationElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      
      // Apply highlight effect for 1 second
      citationElement.style.background = '#f3e6ff';
      setTimeout(() => {
        citationElement.style.background = '';
      }, CITE_HIGHLIGHT_DURATION);
    }
  };

  /**
   * Parses message text and converts citation markers into interactive elements
   * Citation format: [N → Page X] where N is the citation number and X is the page
   * Clicking a citation scrolls to and highlights the corresponding source
   * 
   * @param {string} text - The message text containing citation markers
   * @param {number} messageIndex - The index of the message being rendered
   * @returns {Array<React.ReactElement>|string} Array of text and citation elements, or original text
   */
  const renderTextWithCitations = (text, messageIndex) => {
    const parts = [];
    let lastIndex = 0;
    // Regex to match citation format: [N → Page X]
    const citationRegex = /\[(\d+)\s*→\s*Page\s*(\d+)\]/g;
    let match;

    // Iterate through all citations in the text
    while ((match = citationRegex.exec(text)) !== null) {
      // Add text before this citation
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index));
      }

      // Extract citation data
      const citationNumber = match[1];
      const pageNumber = match[2];
      const fullCitation = match[0]; // e.g., "[1 → Page 4]"
      
      // Create clickable citation element
      parts.push(
        <span
          key={`cite-${match.index}`}
          className="inline-citation"
          onClick={() => scrollToCitation(citationNumber, messageIndex)}
          title={`Click to view source ${citationNumber}`}
        >
          {fullCitation}
        </span>
      );

      lastIndex = match.index + match[0].length;
    }

    // Add any remaining text after the last citation
    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : text;
  };

  /**
   * Handles file uploads from the file input element
   * Uploads selected files to the backend with the current session ID
   * Updates local state with successful uploads and shows status messages
   * 
   * Supported formats: PDF, JPG, JPEG, PNG, TIFF, BMP, DOCX, TXT
   * 
   * @param {Event} event - The change event from the file input element
   */
  const handleFileUpload = async (event) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    const uploadResults = [];

    if (process.env.NODE_ENV === 'development') {
      console.log('📤 Uploading files with session ID:', sessionId);
    }

    try {
      for (const file of files) {
        if (!file || !file.name) continue;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', sessionId);

        if (process.env.NODE_ENV === 'development') {
          console.log('📤 Uploading:', file.name);
        }

        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
          
          const response = await fetch(
            `${API_BASE_URL}/upload`,
            {
              method: 'POST',
              headers: {
                'X-API-Key': API_KEY
              },
              body: formData,
              signal: controller.signal
            }
          );
          
          clearTimeout(timeoutId);

          if (response.ok) {
            const result = await response.json();
            if (process.env.NODE_ENV === 'development') {
              console.log('✅ Upload successful');
            }
            
            uploadResults.push({
              name: file.name,
              success: true,
              pages: result.pages_extracted
            });
          } else {
            uploadResults.push({
              name: file.name,
              success: false
            });
          }
        } catch (uploadError) {
          if (process.env.NODE_ENV === 'development') {
            console.error('Upload error:', uploadError);
          }
          uploadResults.push({
            name: file.name,
            success: false
          });
        }
      }

      setUploadedFiles(prev => [...prev, ...uploadResults.filter(r => r.success)]);

      const successCount = uploadResults.filter(r => r.success).length;
      if (successCount > 0) {
        const systemMessage = {
          role: 'system',
          content: `✓ Uploaded ${successCount} document(s). You can now ask questions about them!`,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, systemMessage]);
      }

      const failedCount = uploadResults.filter(r => !r.success).length;
      if (failedCount > 0) {
        const errorMessage = {
          role: 'system',
          content: `✗ Failed to upload ${failedCount} document(s). Please try again.`,
          timestamp: new Date(),
          error: true
        };
        setMessages(prev => [...prev, errorMessage]);
      }

    } catch (error) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Upload batch error:', error);
      }
      const errorMessage = {
        role: 'system',
        content: '✗ Failed to upload documents. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  /**
   * Handles clearing all uploaded documents for the current session
   * Requires user confirmation before deleting
   * Sends cleanup request to backend and updates UI state
   */
  const handleClearUploads = async () => {
    if (uploadedFiles.length === 0) return;
    
    if (!window.confirm(`Delete ${uploadedFiles.length} uploaded document(s)?`)) {
      return;
    }

    if (process.env.NODE_ENV === 'development') {
      console.log('🗑️ User manually clearing uploads');
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
      
      const response = await fetch(
        `${API_BASE_URL}/cleanup-session`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': API_KEY
          },
          body: JSON.stringify({ session_id: sessionId }),
          signal: controller.signal
        }
      );
      
      clearTimeout(timeoutId);

      if (response.ok) {
        setUploadedFiles([]);
        const systemMessage = {
          role: 'system',
          content: '✓ All uploaded documents have been deleted.',
          timestamp: new Date()
        };
        setMessages(prev => [...prev, systemMessage]);
      } else {
        throw new Error('Failed to clear uploads');
      }
    } catch (error) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Clear error:', error);
      }
      const errorMessage = {
        role: 'system',
        content: '✗ Failed to delete documents. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    }
  };

  /**
   * Handles form submission when user sends a message
   * Validates input, sends message to backend via API, and displays response
   * Response may include inline citations and source documents
   * 
   * @param {Event} e - The form submission event
   */
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const trimmedInput = input.trim();
    if (trimmedInput.length === 0 || trimmedInput.length > 5000) {
      return;
    }

    const userMessage = { role: 'user', content: trimmedInput, timestamp: new Date() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    if (process.env.NODE_ENV === 'development') {
      console.log('💬 Sending chat with session ID:', sessionId);
    }

    try {
      const response = await sendMessage(trimmedInput, sessionId);
      
      if (process.env.NODE_ENV === 'development') {
        console.log('✅ Chat response received');
      }
      
      if (!response?.response) {
        throw new Error('Invalid response from server');
      }
      
      if (!sessionId) {
        if (response.session_id) {
          setSessionId(response.session_id);
        }
      }
      
      const botMessage = {
        role: 'assistant',
        content: response.response,
        sources: response.sources || [],
        timestamp: new Date()
      };
      
      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Chat error:', error);
      }
      const errorMessage = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  // ============ Component Render ============
  
  return (
    <div className="chat-container">
      {/* File Upload Section - Allows users to upload documents for analysis */}
      <div className="upload-section">
        <input
          ref={fileInputRef}
          type="file"
          id="file-upload"
          className="file-input"
          onChange={handleFileUpload}
          accept={SUPPORTED_FORMATS}
          multiple
          disabled={uploading}
        />
        <label htmlFor="file-upload" className={`upload-button ${uploading ? 'uploading' : ''}`}>
          {uploading ? 'Uploading...' : 'Upload Documents'}
        </label>
        {uploadedFiles.length > 0 && (
          <>
            <span className="uploaded-count">
              {uploadedFiles.length} file(s) uploaded
            </span>
            <button 
              className="clear-button"
              onClick={handleClearUploads}
              title="Delete uploaded documents"
            >
              🗑️ Clear
            </button>
          </>
        )}
      </div>

      {/* Messages Container - Displays chat history and system messages */}
      <div className="messages-container">
        {/* Welcome message shown when no messages exist */}
        {messages.length === 0 && (
          <div className="welcome-message">
            <h2>Welcome to YottaReal Assistant</h2>
            <p>Ask me anything about property management policies, procedures, or guidelines.</p>
            <p>I can help you with move-out procedures, lease agreements, maintenance policies, and more.</p>
          </div>
        )}
        
        {/* Render each message in the chat history */}
        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role} ${message.error ? 'error' : ''}`}>
            {/* Regular user and assistant messages */}
            {message.role !== 'system' && (
              <div className="message-content">
                <div className="message-header">
                  <span className="message-label">
                    {message.role === 'user' ? 'You' : 'Yotta'}
                  </span>
                  <span className="message-time">
                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
                <div className="message-text">
                  {message.role === 'assistant' 
                    ? renderTextWithCitations(message.content, index)
                    : message.content}
                </div>
                
                {message.role === 'assistant' && !message.error && (
                  <button 
                    className="copy-button"
                    onClick={() => handleCopy(message.content, index)}
                    title="Copy message"
                  >
                    {copiedIndex === index ? '✓ Copied' : '📋 Copy'}
                  </button>
                )}
                
                {/* Display sources/citations if the message contains them */}
                {message.sources && message.sources.length > 0 && (
                  <div className="citations">
                    <div className="citations-header">
                      <strong>Sources:</strong>
                    </div>
                    <ul className="citations-list">
                      {/* Render each citation source - double-click to download */}
                      {message.sources.map((source, idx) => (
                        <li 
                          key={idx} 
                          className="citation-item"
                          ref={el => citationsRef.current[`${index}-${source.citation_number}`] = el}
                          onDoubleClick={() => handleCitationDownload(source)}
                          style={{ cursor: source.download_url ? 'pointer' : 'default' }}
                        >
                          <span className="citation-number">[{source.citation_number}]</span>
                          <span className="citation-filename">{source.filename}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {/* System messages for upload/cleanup notifications */}
            {message.role === 'system' && (
              <div className={`system-message ${message.error ? 'system-error' : 'system-success'}`}>
                {message.content}
              </div>
            )}
          </div>
        ))}
        
        {/* Loading indicator - animated typing animation while awaiting response */}
        {loading && (
          <div className="message assistant loading">
            <div className="message-content">
              <div className="message-timestamp">Yotta</div>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <span className="typing-text">Yotta is typing...</span>
              </div>
            </div>
          </div>
        )}
        
        {/* Invisible element used for auto-scrolling to latest message */}
        <div ref={messagesEndRef} />
      </div>

      {/* Chat Input Form - For sending messages */}
      <form onSubmit={handleSubmit} className="input-form">
        {/* Text input field for user messages */}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={loading}
          className="message-input"
        />
        {/* Send button - disabled while loading or input is empty */}
        <button type="submit" disabled={loading || !input.trim()} className="send-button">
          Send
        </button>
      </form>
    </div>
  );
}

export default ChatInterface;