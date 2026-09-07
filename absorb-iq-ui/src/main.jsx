import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./App.css";

// A render-time exception anywhere in the tree would otherwise blank the screen
// (worst case on a live demo). Catch it and show a recoverable message instead.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("Uncaught UI error:", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="app-error-boundary">
          <h2>Something went wrong</h2>
          <p>The app hit an unexpected error. Reloading usually fixes it.</p>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
