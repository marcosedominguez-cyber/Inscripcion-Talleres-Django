import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

test.each([
  [false, 'Fuera de plazo: el límite de inscripción ya venció.'],
  [false, 'Superposición de horarios: ya tienes una inscripción confirmada en T-001.'],
  [true, 'Fuera de plazo: el límite de inscripción ya venció.'],
  [true, 'Superposición de horarios: ya tienes una inscripción confirmada en T-001.'],
])('conserva el motivo de rechazo del servicio (espera=%s): %s', async (espera, motivo) => {
  const datos = catalogo(espera ? 0 : 1);
  if (espera) datos.talleres[0].lugares_espera = 1;
  const cargarCatalogo = vi.fn().mockResolvedValueOnce(datos)
    .mockRejectedValue(new Error('Fallo al refrescar el catálogo.'));
  const servicio = espera ? solicitarEspera : inscribirEnTaller;
  servicio.mockRejectedValue(Object.assign(new Error(motivo), { status: 409 }));
  render(<CatalogoParticipante cargarCatalogo={cargarCatalogo}
    usuario={{ nombre_usuario: 'Ana' }} onSesionCaducada={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', {
    name: espera ? 'Entrar en lista de espera' : 'Inscribirme',
  }));

  expect((await screen.findByRole('alert')).textContent).toContain(motivo);
  await waitFor(() => expect(cargarCatalogo).toHaveBeenCalledTimes(2));
  expect(screen.getByRole('alert').textContent).toContain(motivo);
  expect(screen.queryByText('Te inscribiste correctamente.')).toBeNull();
});

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

test('muestra confirmadas y en espera en columnas separadas sin acciones del catálogo', async () => {
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
  expect(await screen.findByRole('heading', { name: 'Mis inscripciones' })).toBeTruthy();
  const confirmadas = screen.getByRole('region', { name: 'Inscripciones confirmadas' });
  const enEspera = screen.getByRole('region', { name: 'Lista de espera' });

  expect(within(confirmadas).getByText('Taller confirmado')).toBeTruthy();
  expect(within(confirmadas).getByText('Confirmada')).toBeTruthy();
  expect(within(confirmadas).queryByText('Taller en espera')).toBeNull();
  expect(within(confirmadas).getByText('Ana Pérez')).toBeTruthy();
  expect(within(confirmadas).getByText('10 personas')).toBeTruthy();
  expect(within(confirmadas).getByText(/10:30/)).toBeTruthy();
  expect(within(confirmadas).getAllByText(/15 oct 2030/).length).toBeGreaterThan(0);
  expect(within(confirmadas).getByText(/08:00/)).toBeTruthy();

  expect(within(enEspera).getByText('Taller en espera')).toBeTruthy();
  expect(within(enEspera).getByText('En espera')).toBeTruthy();
  expect(within(enEspera).queryByText('Taller confirmado')).toBeNull();
  expect(screen.getByText('Horarios en America/La_Paz')).toBeTruthy();
  expect(screen.queryByText('Próximamente')).toBeNull();
  expect(screen.queryByRole('button', { name: /Inscribirme|lista de espera/i })).toBeNull();
});

test('mantiene la otra columna cuando una categoría está vacía', async () => {
  const datos = misInscripciones();
  datos.inscripciones = datos.inscripciones.filter((inscripcion) => inscripcion.estado === 'confirmada');
  render(
    <CatalogoParticipante
      cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
      cargarInscripciones={vi.fn().mockResolvedValue(datos)}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  const confirmadas = await screen.findByRole('region', { name: 'Inscripciones confirmadas' });
  const enEspera = screen.getByRole('region', { name: 'Lista de espera' });
  expect(within(confirmadas).getByText('Taller confirmado')).toBeTruthy();
  expect(within(enEspera).getByText('No tenés solicitudes en espera.')).toBeTruthy();
});

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

test('no recarga el catálogo al cambiar de vista y refresca al volver a inscripciones', async () => {
  const cargarCatalogo = vi.fn().mockResolvedValue(catalogo(1));
  const cargarInscripciones = vi.fn().mockResolvedValue({ inscripciones: [], zona_horaria: 'UTC' });
  render(
    <CatalogoParticipante
      cargarCatalogo={cargarCatalogo}
      cargarInscripciones={cargarInscripciones}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  await screen.findByRole('button', { name: 'Inscribirme' });
  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByRole('heading', { name: 'Mis inscripciones' });
  fireEvent.click(screen.getByRole('button', { name: 'Explorar talleres' }));
  await screen.findByRole('button', { name: 'Inscribirme' });
  expect(cargarCatalogo).toHaveBeenCalledTimes(1);
  expect(cargarInscripciones).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByRole('heading', { name: 'Mis inscripciones' });
  expect(cargarInscripciones).toHaveBeenCalledTimes(2);
});


function respuestaConCancelaciones() {
  return {
    inscripciones: [],
    cancelaciones: [{
      codigo: 'T-001',
      nombre: 'Taller cancelado',
      estado_anterior: 'confirmada',
      fecha_cancelacion: '2030-10-03T12:00:00Z',
    }],
    cancelaciones_consecutivas: 1,
    limite_cancelaciones: 3,
    inscripciones_bloqueadas: false,
    zona_horaria: 'UTC',
  };
}

test('abre el menú, confirma la cancelación y refresca sin mostrar el historial', async () => {
  const cargarInscripciones = vi.fn()
    .mockResolvedValueOnce(misInscripciones())
    .mockResolvedValueOnce(respuestaConCancelaciones());
  const cargarCatalogo = vi.fn().mockResolvedValue(catalogo(1));
  render(
    <CatalogoParticipante
      cargarCatalogo={cargarCatalogo}
      cargarInscripciones={cargarInscripciones}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByText('Taller confirmado');
  fireEvent.click(screen.getByRole('button', { name: 'Acciones para Taller confirmado' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Cancelar inscripción' }));
  expect(screen.getByRole('dialog', { name: 'Cancelar inscripción' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Sí, cancelar' }));

  await waitFor(() => expect(cancelarInscripcion).toHaveBeenCalledWith('T-001'));
  expect((await screen.findByRole('status')).textContent).toContain('Cancelación registrada.');
  expect(screen.queryByRole('heading', { name: 'Historial de cancelaciones' })).toBeNull();
  expect(screen.queryByText('Taller cancelado')).toBeNull();
  expect(cargarInscripciones).toHaveBeenCalledTimes(2);
  expect(cargarCatalogo).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('volver cierra el diálogo sin cancelar', async () => {
  render(
    <CatalogoParticipante
      cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
      cargarInscripciones={vi.fn().mockResolvedValue(misInscripciones())}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByText('Taller confirmado');
  fireEvent.click(screen.getByRole('button', { name: 'Acciones para Taller confirmado' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Cancelar inscripción' }));
  fireEvent.click(screen.getByRole('button', { name: 'Volver' }));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(cancelarInscripcion).not.toHaveBeenCalled();
});

test('muestra el bloqueo sin historial visible', async () => {
  const datos = respuestaConCancelaciones();
  Object.assign(datos, {
    cancelaciones_consecutivas: 3,
    inscripciones_bloqueadas: true,
  });
  render(
    <CatalogoParticipante
      cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
      cargarInscripciones={vi.fn().mockResolvedValue(datos)}
      usuario={{ nombre_usuario: 'Participante' }}
      onSesionCaducada={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  expect((await screen.findByRole('alert')).textContent).toContain(
    'bloqueada para nuevas inscripciones',
  );
  expect(screen.queryByRole('heading', { name: 'Historial de cancelaciones' })).toBeNull();
  expect(screen.queryByText('Taller cancelado')).toBeNull();
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


test('el logo join.a.workshop vuelve al catálogo desde Mis inscripciones', async () => {
  render(<CatalogoParticipante
    cargarCatalogo={vi.fn().mockResolvedValue(catalogo(1))}
    cargarInscripciones={vi.fn().mockResolvedValue(misInscripciones())}
    usuario={{ nombre_usuario: 'Participante' }} onSesionCaducada={vi.fn()} />);
  await screen.findByRole('button', { name: 'Inscribirme' });
  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByText('Taller confirmado');
  const marca = screen.getByRole('link', { name: 'join.a.workshop, ir al catálogo' });
  expect(marca.querySelector('svg')).toBeTruthy();
  fireEvent.click(marca);
  expect(screen.getByRole('heading', { name: 'Próximos talleres' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Mis inscripciones' }));
  await screen.findByText('Taller confirmado');
  fireEvent.click(screen.getByRole('button', { name: 'Acciones para Taller confirmado' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Cancelar inscripción' }));
  expect(screen.getByRole('dialog', { name: 'Cancelar inscripción' })).toBeTruthy();
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
