// === main.jsx: the entry point ==============================================
// React concept: "mounting". A React app is an ordinary JS program that takes
// over one DOM element (the <div id="root"> in index.html) and renders a tree
// of components into it. Everything else on the page is React's from here on.
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

// createRoot() is the React 18 API for attaching React to a DOM node.
// <App /> is JSX: syntax sugar for "create an element of the App component".
//
// <React.StrictMode> is a development-only helper: it double-invokes renders
// and effects to surface accidental side effects early. It renders nothing
// and does nothing in the production build.
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
