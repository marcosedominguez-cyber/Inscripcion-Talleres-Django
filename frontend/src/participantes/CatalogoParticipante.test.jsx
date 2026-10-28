import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import CatalogoParticipante from './CatalogoParticipante.jsx';
import { inscribirEnTaller, solicitarEspera } from './api.js';

vi.mock('./api.js', () => ({
  obtenerCatalogo: vi.fn(),
  inscribirEnTaller: vi.fn(),
  solicitarEspera: vi.fn(),
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


test('solicita espera y recupera su posición del catálogo actualizado', async () => {
  const inicial = catalogo(0);
  Object.assign(inicial.talleres[0], { lugares_espera: 1, limite_espera: 2 });
  const actualizado = catalogo(0);
  Object.assign(actualizado.talleres[0], { mi_estado: 'en_espera', posicion_espera: 2 });
  const cargarCatalogo = vi.fn().mockResolvedValueOnce(inicial).mockResolvedValue(actualizado);
  solicitarEspera.mockResolvedValue({ mensaje: 'Solicitud admitida en la lista de espera.' });
  render(<CatalogoParticipante cargarCatalogo={cargarCatalogo} usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Entrar en lista de espera' }));
  await screen.findByRole('button', { name: 'En espera · Posición 2' });
  expect(solicitarEspera).toHaveBeenCalledWith('T-001');
  expect(screen.getByRole('button', { name: 'En espera · Posición 2' }).disabled).toBe(true);
});

test('una espera llena bloquea el envío', async () => {
  render(<CatalogoParticipante cargarCatalogo={vi.fn().mockResolvedValue(catalogo(0))} usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  expect((await screen.findByRole('button', { name: 'Lista de espera llena' })).disabled).toBe(true);
});


test('si otra solicitud llena la espera muestra el rechazo y actualiza la tarjeta', async () => {
  const inicial = catalogo(0);
  inicial.talleres[0].lugares_espera = 1;
  const cargarCatalogo = vi.fn().mockResolvedValueOnce(inicial).mockResolvedValue(catalogo(0));
  solicitarEspera.mockRejectedValue(Object.assign(new Error('La lista de espera está llena.'), { status: 409 }));
  render(<CatalogoParticipante cargarCatalogo={cargarCatalogo} usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Entrar en lista de espera' }));
  expect((await screen.findByRole('alert')).textContent).toContain('La lista de espera está llena.');
  expect((await screen.findByRole('button', { name: 'Lista de espera llena' })).disabled).toBe(true);
});
