import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from './App.jsx';
import { solicitudApi } from './api.js';
import { api } from './cuentas/api.js';

vi.mock('./api.js', () => ({ solicitudApi: vi.fn() }));
vi.mock('./cuentas/api.js', () => ({ api: vi.fn() }));
beforeEach(() => {
  api.mockReset();
  solicitudApi.mockReset();
  api.mockResolvedValue({ usuario: null });
  solicitudApi.mockResolvedValue({ talleres: [] });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test('registro de instructor envía su rol y vuelve al login sin autenticar', async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: '¿Quieres publicar talleres?' }));
  fireEvent.change(screen.getByLabelText('Nombre de usuario'), { target: { value: 'profesor' } });
  fireEvent.change(screen.getByLabelText('CI'), { target: { value: '12345678' } });
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'Clave!742segura' } });
  fireEvent.change(screen.getByLabelText('Confirmar contraseña'), { target: { value: 'Clave!742segura' } });
  api.mockImplementation(async (ruta) => ruta === 'registro' ? { mensaje: 'Cuenta creada.' } : { usuario: null });
  fireEvent.click(screen.getByRole('button', { name: 'Crear cuenta' }));
  await screen.findByRole('heading', { name: 'Iniciar sesión' });
  expect(api).toHaveBeenCalledWith('registro', expect.objectContaining({ rol: 'instructor', ci: '12345678' }));
  expect(api.mock.calls.some(([ruta]) => ruta === 'login')).toBe(false);
  expect(screen.queryByLabelText('Confirmar contraseña')).toBeNull();
  expect(screen.getByLabelText('Contraseña').value).toBe('');
});


test('un rechazo del servidor se muestra sin abrir la cuenta', async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Descubrir talleres' }));
  fireEvent.change(screen.getByLabelText('CI'), { target: { value: '1234' } });
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'incorrecta' } });
  api.mockImplementation(async (ruta) => {
    if (ruta === 'login') throw new Error('CI o contraseña incorrectas.');
    return { usuario: null };
  });
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }));
  expect((await screen.findByRole('alert')).textContent).toBe('CI o contraseña incorrectas.');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Ingresar' }).disabled).toBe(false));
  expect(screen.queryByText('Sesión iniciada')).toBeNull();
  expect(api).toHaveBeenCalledWith('login', { ci: '1234', contrasena: 'incorrecta', rol: 'participante' });
  fireEvent.click(screen.getByRole('button', { name: 'Instructor', exact: true }));
  fireEvent.change(screen.getByLabelText('CI'), { target: { value: '1234' } });
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'correcta' } });
  api.mockImplementation(async (ruta) => {
    if (ruta === 'login') throw new Error('La cuenta no corresponde al tipo de acceso seleccionado.');
    return { usuario: null };
  });
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }));
  expect((await screen.findByRole('alert')).textContent).toBe('La cuenta no corresponde al tipo de acceso seleccionado.');
  expect(api).toHaveBeenCalledWith('login', { ci: '1234', contrasena: 'correcta', rol: 'instructor' });
  expect(screen.getByRole('button', { name: 'Instructor', exact: true }).getAttribute('aria-pressed')).toBe('true');
  expect(screen.queryByRole('heading', { name: 'Proponer un taller' })).toBeNull();
});


test('instructor consulta participantes en espera de su taller', async () => {
  api.mockResolvedValue({ usuario: { rol: 'instructor', nombre_usuario: 'Profesor' } });
  solicitudApi.mockImplementation(async (ruta) => ruta.endsWith('/espera/')
    ? { solicitudes: [{ posicion: 1, nombre: 'Ana Espera', fecha_solicitud: '2030-10-15T09:00:00Z' }] }
    : { talleres: [{ codigo: 'T-001', nombre: 'Taller', cupos: 5, confirmadas: 5, plazas_libres: 0 }] });
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Ver lista de espera' }));
  await screen.findByText(/Ana Espera/);
  expect(solicitudApi).toHaveBeenCalledWith('/api/gestion/talleres/T-001/espera/');
});


test('el instructor crea una propuesta desde el nuevo formulario', async () => {
  api.mockResolvedValue({ usuario: { rol: 'instructor', nombre_usuario: 'Ana' } });
  solicitudApi.mockResolvedValue({ talleres: [] });
  render(<App />);
  await screen.findByRole('heading', { name: 'Proponer un taller' });
  fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'Introducción a cerámica' } });
  fireEvent.change(screen.getByLabelText('Descripción'), { target: { value: 'Aprende a crear tu primera pieza.' } });
  fireEvent.change(screen.getByLabelText('Cupo máximo'), { target: { value: '10' } });
  fireEvent.change(screen.getByLabelText('Inicio (hora de Bolivia)'), { target: { value: '2030-11-01T09:00' } });
  fireEvent.change(screen.getByLabelText('Fin (hora de Bolivia)'), { target: { value: '2030-11-02T09:00' } });
  fireEvent.click(screen.getByRole('button', { name: 'Enviar propuesta' }));
  await screen.findByText('Propuesta enviada para aprobación.');
  expect(solicitudApi).toHaveBeenCalledWith('/api/gestion/talleres/', { method: 'POST', datos: {
    nombre: 'Introducción a cerámica', descripcion: 'Aprende a crear tu primera pieza.', cupos: 10,
    fecha_inicio: '2030-11-01T09:00', fecha_fin: '2030-11-02T09:00',
  } });
});
