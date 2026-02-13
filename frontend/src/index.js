/**
 * Application Entry Point
 * 
 * This is the main entry point for the YottaReal Bot React application.
 * It is responsible for:
 * - Importing the root React component (App)
 * - Initializing the React application
 * - Mounting the application to the DOM
 * - Rendering global styles
 * 
 * This file is called by webpack bundler during the build process and
 * serves as the starting point for the entire React component tree.
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

// ============ Application Initialization ============

// Get the root DOM element where React will mount
// This corresponds to the <div id="root"></div> in public/index.html
const root = ReactDOM.createRoot(document.getElementById('root'));

// Render the App component into the root element
// React.StrictMode enables additional development checks and warnings
root.render(
  // StrictMode wraps the app and provides helpful debugging information during development
  // It identifies potential problems with component code but has no effect in production
  <React.StrictMode>
    {/* Root App component - contains all other components and establishes the layout */}
    <App />
  </React.StrictMode>
);