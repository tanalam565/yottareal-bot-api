/**
 * API Service Module
 * 
 * Handles all HTTP communication with the backend API.
 * Configures axios instance with base URL, timeout, and authentication headers.
 * Provides methods for chat and health check endpoints.
 */

import axios from 'axios';

// ============ Configuration ============

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';
const API_KEY = process.env.REACT_APP_CHATBOT_API_KEY || '';
const REQUEST_TIMEOUT = 30000; // 30 seconds

// Validate critical environment variables
if (!API_BASE_URL) {
  console.error('CRITICAL: API_BASE_URL is not configured');
}

/**
 * Axios instance with pre-configured headers and timeout
 * @type {AxiosInstance}
 */
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY
  },
});

/**
 * Sends a message to the chatbot API
 * 
 * @async
 * @param {string} messageText - The user's message
 * @param {string} sessionId - Unique session identifier for tracking context
 * @returns {Promise<Object>} Response data with assistant message and sources
 * @throws {Error} If the request fails
 */
export const sendMessage = async (messageText, sessionId = null) => {
  try {
    if (!messageText || typeof messageText !== 'string') {
      throw new Error('Invalid message text');
    }

    const response = await api.post('/chat', {
      message: messageText.trim(),
      session_id: sessionId,
    });
    
    return response.data;
  } catch (error) {
    // Log only in development
    if (process.env.NODE_ENV === 'development') {
      console.error('Chat API error:', error.message);
    }
    
    // Re-throw with user-friendly message in production
    if (error.response?.status === 401) {
      throw new Error('Authentication failed');
    } else if (error.request && !error.response) {
      throw new Error('Network error: Unable to reach server');
    }
    throw error;
  }
};

/**
 * Checks if the API server is healthy
 * 
 * @async
 * @returns {Promise<Object>} Health status information
 * @throws {Error} If health check fails
 */
export const checkHealth = async () => {
  try {
    const response = await api.get('/health');
    return response.data;
  } catch (error) {
    if (process.env.NODE_ENV === 'development') {
      console.error('Health check failed:', error.message);
    }
    throw error;
  }
};

export default api;