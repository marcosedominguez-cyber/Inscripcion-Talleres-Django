import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import Demo from './demo.jsx';

const Pantalla = import.meta.env.MODE === 'demo' ? Demo : App;

createRoot(document.getElementById('root')).render(
  <StrictMode><Pantalla /></StrictMode>,
);
