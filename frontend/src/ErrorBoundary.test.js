import React from 'react';
import { render, screen } from '@testing-library/react';
import ErrorBoundary from './ErrorBoundary';

function Bomb() {
  throw new Error('boom');
}

test('renders a fallback message instead of a blank page when a child throws', () => {
  // React logs the error to console.error too; silence it for this test.
  const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});

  render(
    <ErrorBoundary>
      <Bomb />
    </ErrorBoundary>
  );

  expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  consoleError.mockRestore();
});

test('renders children normally when nothing throws', () => {
  render(
    <ErrorBoundary>
      <p>All good</p>
    </ErrorBoundary>
  );

  expect(screen.getByText('All good')).toBeInTheDocument();
});
