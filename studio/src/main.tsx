import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

type ErrorFallbackState = {
  error: Error | null;
};

class ErrorBoundary extends React.Component<React.PropsWithChildren, ErrorFallbackState> {
  state: ErrorFallbackState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorFallbackState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("Studio render failed", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="studioCrash">
        <section>
          <p className="eyebrow">Asteria Studio</p>
          <h1>Studio failed to render</h1>
          <p>The frontend hit a recoverable rendering error. The details are shown below so the page doesn't go fully blank.</p>
          <pre>{this.state.error.stack || this.state.error.message}</pre>
          <button onClick={() => window.location.reload()}>Reload Studio</button>
        </section>
      </main>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
