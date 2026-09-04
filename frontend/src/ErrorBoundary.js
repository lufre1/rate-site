import React from 'react';
import i18n from 'i18next';

// This renders OUTSIDE the i18n-initialised tree (index.js wraps App, which is
// what calls init), and it exists to survive a crash -- possibly one that
// happened before init ran. So check first and fall back to the literal, which
// is also what ErrorBoundary.test.js renders against in isolation.
const tr = (key, fallback) => (i18n.isInitialized ? i18n.t(key, fallback) : fallback);

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
          <p className="empty__text">
            {tr('ui.fatalError', 'Something went wrong. Please reload the page.')}
          </p>
          <button type="button" className="btn btn--primary"
            onClick={() => window.location.reload()}>
            {tr('ui.reload', 'Reload')}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
