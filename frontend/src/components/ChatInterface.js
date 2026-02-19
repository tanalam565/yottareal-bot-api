// frontend/src/components/ChatInterface.js - WITH INLINE CITATIONS PARSING [N → Page X]

import React, { useState, useRef, useEffect } from 'react';
import { sendMessage } from '../services/api';
import './ChatInterface.css';

function ChatInterface() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    return `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  });
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [uploadsRemaining, setUploadsRemaining] = useState(5); // Track remaining uploads
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const citationsRef = useRef({});

  useEffect(() => {
    console.log('🔑 Session ID:', sessionId);
  }, [sessionId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    const cleanupSession = async () => {
      if (uploadedFiles.length > 0 && sessionId) {
        console.log('🗑️ Cleaning up session on unmount:', sessionId);
        try {
          await fetch(
            `${process.env.REACT_APP_API_URL}/cleanup-session`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-API-Key': process.env.REACT_APP_CHATBOT_API_KEY || ''
              },
              body: JSON.stringify({ session_id: sessionId }),
              keepalive: true
            }
          );
        } catch (error) {
          console.error('Cleanup error:', error);
        }
      }
    };

    const handleBeforeUnload = (e) => {
      if (uploadedFiles.length > 0) {
        cleanupSession();
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      cleanupSession();
    };
  }, []);

  const handleCopy = (text, index) => {
    const cleanText = text.replace(/\[(\d+)\s*→\s*Page\s*\d+\]/g, '');
    navigator.clipboard.writeText(cleanText).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    }).catch(err => {
      console.error('Failed to copy:', err);
    });
  };

  const handleCitationDownload = async (source) => {
    if (!source.download_url) {
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
      console.log('✅ Download initiated:', source.filename);
    } catch (error) {
      console.error('Download error:', error);
    }
  };

  const scrollToCitation = (citationNumber, messageIndex) => {
    const citationElement = citationsRef.current[`${messageIndex}-${citationNumber}`];
    if (citationElement) {
      citationElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      citationElement.style.background = '#f3e6ff';
      setTimeout(() => {
        citationElement.style.background = '';
      }, 1000);
    }
  };

  const renderTextWithCitations = (text, messageIndex) => {
    const parts = [];
    let lastIndex = 0;
    const citationRegex = /\[(\d+)\s*→\s*Page\s*(\d+)\]/g;
    let match;

    while ((match = citationRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index));
      }

      const citationNumber = match[1];
      const fullCitation = match[0];

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

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : text;
  };

  const handleFileUpload = async (event) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    // Client-side file size validation
    const MAX_FILE_SIZE_MB = 15;
    const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

    for (const file of files) {
      if (file.size > MAX_FILE_SIZE_BYTES) {
        const errorMessage = {
          role: 'system',
          content: `✗ "${file.name}" exceeds the ${MAX_FILE_SIZE_MB}MB limit. Please upload a smaller file.`,
          timestamp: new Date(),
          error: true
        };
        setMessages(prev => [...prev, errorMessage]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }
    }

    setUploading(true);
    const uploadResults = [];

    console.log('📤 Uploading files with session ID:', sessionId);

    try {
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', sessionId);

        console.log('📤 Uploading:', file.name, 'with session:', sessionId);

        const response = await fetch(
          `${process.env.REACT_APP_API_URL}/upload`,
          {
            method: 'POST',
            headers: {
              'X-API-Key': process.env.REACT_APP_CHATBOT_API_KEY || ''
            },
            body: formData
          }
        );

        if (response.ok) {
          const result = await response.json();
          console.log('✅ Upload successful. Backend returned session:', result.session_id);

          uploadResults.push({
            name: file.name,
            success: true,
            pages: result.pages_extracted
          });

          // Update remaining uploads
          if (result.uploads_remaining !== undefined) {
            setUploadsRemaining(result.uploads_remaining);
          }
        } else {
          const error = await response.json();
          uploadResults.push({
            name: file.name,
            success: false,
            error: error.detail || 'Upload failed'
          });
        }
      }

      setUploadedFiles(prev => [...prev, ...uploadResults.filter(r => r.success)]);

      const successCount = uploadResults.filter(r => r.success).length;
      const failedCount = uploadResults.filter(r => !r.success).length;

      if (successCount > 0) {
        const successFiles = uploadResults.filter(r => r.success);
        const fileDetails = successFiles.map(f =>
          `${f.name} (${f.pages} page${f.pages !== 1 ? 's' : ''} read)`
        ).join(', ');

        const systemMessage = {
          role: 'system',
          content: `✓ Uploaded ${successCount} document(s): ${fileDetails}. Note: Only the first 15 pages of each file are read.`,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, systemMessage]);
      }

      if (failedCount > 0) {
        const failedFiles = uploadResults.filter(r => !r.success);
        const errorDetails = failedFiles.map(f =>
          `${f.name}: ${f.error || 'Upload failed'}`
        ).join('; ');

        const errorMessage = {
          role: 'system',
          content: `✗ Failed to upload ${failedCount} document(s). ${errorDetails}`,
          timestamp: new Date(),
          error: true
        };
        setMessages(prev => [...prev, errorMessage]);
      }

    } catch (error) {
      console.error('Upload error:', error);
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

  const handleClearUploads = async () => {
    if (uploadedFiles.length === 0) return;

    if (!window.confirm(`Delete ${uploadedFiles.length} uploaded document(s)?`)) {
      return;
    }

    console.log('🗑️ User manually clearing uploads');

    try {
      const response = await fetch(
        `${process.env.REACT_APP_API_URL}/cleanup-session`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': process.env.REACT_APP_CHATBOT_API_KEY || ''
          },
          body: JSON.stringify({ session_id: sessionId })
        }
      );

      if (response.ok) {
        setUploadedFiles([]);
        setUploadsRemaining(5); // Reset to max
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
      console.error('Clear error:', error);
      const errorMessage = {
        role: 'system',
        content: '✗ Failed to delete documents. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input, timestamp: new Date() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    console.log('💬 Sending chat with session ID:', sessionId);
    console.log('📊 Uploaded files count:', uploadedFiles.length);

    try {
      const response = await sendMessage(input, sessionId);

      console.log('✅ Chat response received');
      console.log('🔑 Backend returned session ID:', response.session_id);
      console.log('📚 Sources count:', response.sources?.length || 0);

      if (!sessionId || sessionId === 'temp') {
        setSessionId(response.session_id);
      } else if (response.session_id !== sessionId) {
        console.warn('⚠️ Backend returned different session ID!');
      }

      const botMessage = {
        role: 'assistant',
        content: response.response,
        sources: response.sources,
        timestamp: new Date()
      };

      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      console.error('Chat error:', error);
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

  return (
    <div className="chat-container">
      <div className="upload-section">
        <input
          ref={fileInputRef}
          type="file"
          id="file-upload"
          className="file-input"
          onChange={handleFileUpload}
          accept=".pdf,.jpg,.jpeg,.png,.tiff,.bmp,.docx,.txt"
          multiple
          disabled={uploading || uploadsRemaining === 0}
        />
        <label htmlFor="file-upload" className={`upload-button ${uploading || uploadsRemaining === 0 ? 'uploading' : ''}`}>
          {uploading ? 'Uploading...' : uploadsRemaining === 0 ? 'Upload Limit Reached' : 'Upload Documents'}
        </label>
        <span className="upload-limits">Max 15MB · First 15 pages · {uploadsRemaining} uploads left</span>
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

      <div className="messages-container">
        {messages.length === 0 && (
          <div className="welcome-message">
            <h2>Welcome to YottaReal Assistant</h2>
            <p>Ask me anything about property management policies, procedures, or guidelines.</p>
            <p>I can help you with move-out procedures, lease agreements, maintenance policies, and more.</p>
          </div>
        )}

        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role} ${message.error ? 'error' : ''}`}>
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

                {message.sources && message.sources.length > 0 && (
                  <div className="citations">
                    <div className="citations-header">
                      <strong>Sources:</strong>
                    </div>
                    <ul className="citations-list">
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
            {message.role === 'system' && (
              <div className={`system-message ${message.error ? 'system-error' : 'system-success'}`}>
                {message.content}
              </div>
            )}
          </div>
        ))}

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

        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="input-form">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={loading}
          className="message-input"
        />
        <button type="submit" disabled={loading || !input.trim()} className="send-button">
          Send
        </button>
      </form>
    </div>
  );
}

export default ChatInterface;