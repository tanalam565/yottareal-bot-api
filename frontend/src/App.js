import React from 'react';
import ChatInterface from './components/ChatInterface';
import './App.css';

function App() {
  const currentYear = new Date().getFullYear();
  
  return (
    <div className="app">
      <header className="site-header">
        <div className="wordmark">
          <div className="name">
            <span className="yotta">YOTTA</span>
            <span className="real">REAL</span>
          </div>
          <div className="tagline">SMART PARTNER</div>
        </div>
      </header>
      
      <main className="chat-main">
        <ChatInterface />
      </main>
      
      <footer className="site-footer">
        <small className="copyright">© {currentYear} YottaReal</small>
      </footer>
    </div>
  );
}

export default App;