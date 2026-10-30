import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import CatalogoParticipante from './CatalogoParticipante.jsx';
import {
  cancelarInscripcion, inscribirEnTaller, obtenerMisInscripciones, solicitarEspera,
  obtenerNotificaciones, marcarNotificacionLeida,
} from './api.js';

vi.mock('./api.js', () => ({
  obtenerCatalogo: vi.fn(),
  obtenerMisInscripciones: vi.fn(),
  inscribirEnTaller: vi.fn(),
  solicitarEspera: vi.fn(),
  obtenerNotificaciones: vi.fn().mockResolvedValue({ notificaciones: [], no_leidas: 0 }),
  marcarNotificacionLeida: vi.fn(),
  cancelarInscripcion: vi.fn(),
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
  obtenerNotificaciones.mockReset();
  obtenerNotificaciones.mockResolvedValue({ notificaciones: [], no_leidas: 0, siguiente: null });
  marcarNotificacionLeida.mockReset();
  marcarNotificacionLeida.mockResolvedValue({ mensaje: 'Notificación leída.' });
  inscribirEnTaller.mockReset();
  solicitarEspera.mockReset();
  inscribirEnTaller.mockResolvedValue({ mensaje: 'Te inscribiste correctamente.' });
  obtenerMisInscripciones.mockReset();
  obtenerMisInscripciones.mockResolvedValue({ inscripciones: [], zona_horaria: 'UTC' });
  cancelarInscripcion.mockReset();
  cancelarInscripcion.mockResolvedValue({ mensaje: 'Cancelación registrada.' });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });


test('conserva el motivo del backend aunque falle el refresco del catálogo', async () => {
  const fallo = new Error('El taller no tiene cupos disponibles.');
  fallo.status = 409;
  inscribirEnTaller.mockRejectedValue(fallo);
  const cargarCatalogo = vi.fn().mockResolvedValueOnce(catalogo(1)).mockRejectedValue(new Error('Falló el refresco'));
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


test('una espera llena bloquea el envío', async () => {
  render(<CatalogoParticipante cargarCatalogo={vi.fn().mockResolvedValue(catalogo(0))} usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  expect((await screen.findByRole('button', { name: 'Lista de espera llena' })).disabled).toBe(true);
});


function misInscripciones() {
  return {
    inscripciones: [
      {
        codigo: 'T-001',
        nombre: 'Taller confirmado',
        descripcion: 'Descripción confirmada',
        cupos: 10,
        fecha_inicio: '2030-10-15T14:30:00Z',
        fecha_fin: '2030-10-15T16:30:00Z',
        instructor: 'Ana Pérez',
        fecha_solicitud: '2030-10-01T12:00:00Z',
        estado: 'confirmada',
      },
      {
        codigo: 'T-002',
        nombre: 'Taller en espera',
        descripcion: '',
        cupos: 5,
        fecha_inicio: '2030-10-20T18:00:00Z',
        fecha_fin: '2030-10-20T20:00:00Z',
        instructor: null,
        fecha_solicitud: '2030-10-02T12:00:00Z',
        estado: 'en_espera',
      },
    ],
    zona_horaria: 'America/La_Paz',
  };
}


test('muestra un error y permite reintentar la consulta de inscripciones', async () => {
  const fallo = Object.assign(new Error('No se pudieron consultar tus inscripciones.'), { status: 503 });
  const cargarInscripciones = vi.fn()
    .mockRejectedValueOnce(fallo)
    .mockResolvedValueOnce(misInscripciones());
  render(
    <CatalogoParticipante
      cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
      cargarInscripciones={cargarInscripciones}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  expect((await screen.findByRole('alert')).textContent).toContain('No pudimos cargar tus inscripciones.');
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
  expect(await screen.findByText('Taller confirmado')).toBeTruthy();
  expect(cargarInscripciones).toHaveBeenCalledTimes(2);
});


test('muestra el error del backend al cancelar sin refrescar', async () => {
  const fallo = Object.assign(new Error('El taller ya comenzó; no se puede cancelar.'), {
    status: 409,
  });
  cancelarInscripcion.mockRejectedValue(fallo);
  const cargarInscripciones = vi.fn().mockResolvedValue(misInscripciones());
  render(
    <CatalogoParticipante
      cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
      cargarInscripciones={cargarInscripciones}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByText('Taller confirmado');
  fireEvent.click(screen.getByRole('button', { name: 'Acciones para Taller confirmado' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Cancelar inscripción' }));
  fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar' }));

  expect((await screen.findByRole('alert')).textContent).toContain(
    'El taller ya comenzó; no se puede cancelar.',
  );
  expect(cargarInscripciones).toHaveBeenCalledTimes(1);
});


function aviso(id, tipo = 'promocion') {
  return { id, tipo, titulo: tipo === 'promocion' ? '¡Tu plaza está confirmada!' : 'Cambios en tu taller',
    mensaje: 'Hay novedades para ti.', fecha: '2030-10-15T10:00:00Z', leida: false };
}

test('la campana muestra una promoción y permite marcarla como leída', async () => {
  obtenerNotificaciones.mockResolvedValue({ notificaciones: [aviso('aviso-1')], no_leidas: 1 });
  render(<CatalogoParticipante cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
    usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Notificaciones, 1 sin leer' }));
  expect(screen.getByRole('heading', { name: '¡Tu plaza está confirmada!' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Marcar como leída' }));
  await waitFor(() => expect(marcarNotificacionLeida).toHaveBeenCalledWith('aviso-1'));
  await screen.findByRole('button', { name: 'Notificaciones, 0 sin leer' });
  expect(screen.queryByRole('button', { name: 'Marcar como leída' })).toBeNull();
});

test('llegan avisos automáticamente y se refresca el catálogo', async () => {
  const { act } = await import('@testing-library/react');
  vi.useFakeTimers();
  obtenerNotificaciones.mockResolvedValueOnce({ notificaciones: [], no_leidas: 0 })
    .mockResolvedValue({ notificaciones: [aviso('nuevo', 'edicion_taller')], no_leidas: 1 });
  const cargarCatalogo = vi.fn().mockResolvedValue(catalogo(1));
  render(<CatalogoParticipante cargarCatalogo={cargarCatalogo} usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(screen.getByRole('button', { name: 'Notificaciones, 1 sin leer' })).toBeTruthy();
  expect(cargarCatalogo).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('status').textContent).toContain('Cambios en tu taller');
});

test('fallo de lectura conserva el aviso sin leer', async () => {
  obtenerNotificaciones.mockResolvedValue({ notificaciones: [aviso('a')], no_leidas: 1 });
  marcarNotificacionLeida.mockRejectedValue(new Error('Sin conexión'));
  render(<CatalogoParticipante cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
    usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Notificaciones, 1 sin leer' }));
  fireEvent.click(screen.getByRole('button', { name: 'Marcar como leída' }));
  expect((await screen.findByRole('alert')).textContent).toContain('No se pudo marcar');
  expect(screen.getByRole('button', { name: 'Notificaciones, 1 sin leer' })).toBeTruthy();
});

test('se pueden consultar notificaciones anteriores', async () => {
  obtenerNotificaciones.mockResolvedValueOnce({ notificaciones: [aviso('b')], no_leidas: 2, siguiente: 'b' })
    .mockResolvedValue({ notificaciones: [aviso('a', 'edicion_taller')], no_leidas: 2, siguiente: null });
  render(<CatalogoParticipante cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
    usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Notificaciones, 2 sin leer' }));
  fireEvent.click(screen.getByRole('button', { name: 'Ver anteriores' }));
  await screen.findByRole('heading', { name: 'Cambios en tu taller' });
  expect(obtenerNotificaciones).toHaveBeenCalledWith({ antes: 'b' });
});
