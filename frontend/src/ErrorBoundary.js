import React, { Component } from 'react';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          <h1>Etwas ist schiefgelaufen</h1>
          <p>Ein Fehler ist aufgetreten. Bitte laden Sie die Seite neu.</p>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
