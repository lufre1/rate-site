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
        <div className="fatal" role="alert">
          <span className="empty__icon" aria-hidden="true">😵</span>
          <p className="empty__text">Something went wrong. Please reload the page.</p>
          <button type="button" className="btn btn--primary"
            onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
