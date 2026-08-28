import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Sans ça, une exception non attrapée pendant le rendu démonte tout React
 * et laisse un écran vide, indiscernable d'une vraie fenêtre plantée vu que
 * le fond de page est déjà sombre. Ici on affiche l'erreur à la place. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("crash React :", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, color: "#e06c75", fontFamily: "monospace" }}>
          <h2>Triton a planté</h2>
          <p>{this.state.error.message}</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{this.state.error.stack}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}
