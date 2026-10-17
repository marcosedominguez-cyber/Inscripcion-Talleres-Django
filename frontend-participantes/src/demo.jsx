import App from './App.jsx';

const ejemplos = {
  usuario: { nombre: 'Ismael' },
  zona_horaria: 'America/La_Paz',
  talleres: [
    { codigo: 'T-001', nombre: 'Introducción a Python', descripcion: 'Dale forma a tus primeras ideas con código. Un taller práctico para empezar desde cero.', cupos: 5, fecha_inicio: '2026-10-20T14:00:00Z', fecha_fin: '2026-10-20T16:00:00Z' },
    { codigo: 'T-002', nombre: 'Hablar con confianza', descripcion: 'Aprendé a comunicar tus ideas con claridad y prepará tu próxima presentación.', cupos: 15, fecha_inicio: '2026-10-21T19:00:00Z', fecha_fin: '2026-10-21T21:00:00Z' },
    { codigo: 'T-003', nombre: 'Diseño de interfaces', descripcion: 'Explorá los principios del diseño y creá pantallas que sean claras y fáciles de usar.', cupos: 12, fecha_inicio: '2026-10-23T13:00:00Z', fecha_fin: '2026-10-23T16:00:00Z' },
  ],
};

const cargarEjemplos = () => Promise.resolve(ejemplos);

export default function Demo() {
  return <App cargarCatalogo={cargarEjemplos} />;
}
