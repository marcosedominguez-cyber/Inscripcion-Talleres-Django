import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import CatalogoParticipante from './CatalogoParticipante.jsx';
import { inscribirEnTaller } from './api.js';

vi.mock('./api.js', () => ({
  obtenerCatalogo: vi.fn(),
  inscribirEnTaller: vi.fn(),
}));

function catalogo(disponibles) {
  return {
    talleres: [{
      codigo: 'T-001',
      nombre: 'Taller de prueba',
      descripcion: '',
      cupos: 3,
      cupos_disponibles: disponibles,
      fecha_inicio: '2030-10-15T10:00:00Z',
      fecha_fin: '2030-10-15T12:00:00Z',
    }],
    zona_horaria: 'UTC',
    usuario: { nombre: 'Participante' },
  };
}

beforeEach(() => {
  inscribirEnTaller.mockReset();
  inscribirEnTaller.mockResolvedValue({ mensaje: 'Te inscribiste correctamente.' });
});
afterEach(cleanup);

test('inscribirse confirma el resultado y refresca los cupos sin recargar la página', async () => {
  const cargarCatalogo = vi.fn()
    .mockResolvedValueOnce(catalogo(2))
    .mockResolvedValueOnce(catalogo(1));
  render(
    <CatalogoParticipante
      cargarCatalogo={cargarCatalogo}
      usuario={{ nombre_usuario: 'Participante' }}
      onCerrarSesion={vi.fn()}
      onSesionCaducada={vi.fn()}
      enviando={false}
      error=""
    />,
  );

  fireEvent.click(await screen.findByRole('button', { name: 'Inscribirme' }));
  expect((await screen.findByRole('status')).textContent).toContain('Te inscribiste correctamente.');
  await waitFor(() => expect(cargarCatalogo).toHaveBeenCalledTimes(2));
  expect(inscribirEnTaller).toHaveBeenCalledWith('T-001');
  expect(document.querySelector('.pw-capacity strong:last-child').textContent).toBe('1');
});

test('muestra un error comprensible enviado por el backend', async () => {
  const fallo = new Error('El taller no tiene cupos disponibles.');
  fallo.status = 409;
  inscribirEnTaller.mockRejectedValue(fallo);
  const cargarCatalogo = vi.fn().mockResolvedValue(catalogo(1));
  render(
    <CatalogoParticipante
      cargarCatalogo={cargarCatalogo}
      usuario={{ nombre_usuario: 'Participante' }}
      onCerrarSesion={vi.fn()}
      onSesionCaducada={vi.fn()}
      enviando={false}
      error=""
    />,
  );

  fireEvent.click(await screen.findByRole('button', { name: 'Inscribirme' }));
  expect((await screen.findByRole('alert')).textContent).toContain('El taller no tiene cupos disponibles.');
  await waitFor(() => expect(cargarCatalogo).toHaveBeenCalledTimes(2));
});
