import React from 'react';

// Catches render errors anywhere below it so a bug in one part of the page
// (e.g. a crash while rendering reviews) shows a message instead of a blank
// white tab.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error('Uncaught error in app:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '100vh', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 12,
          fontFamily: '-apple-system, sans-serif', padding: 20, textAlign: 'center',
        }}>
          <p style={{ fontSize: '1rem', color: '#374151' }}>
            Something went wrong. Please reload the page.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '0.5rem 1rem', borderRadius: '0.5rem', border: 'none',
              background: '#3b82f6', color: '#fff', cursor: 'pointer', fontSize: '0.875rem',
            }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
