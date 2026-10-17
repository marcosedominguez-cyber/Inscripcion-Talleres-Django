import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from './App.jsx';
import { api } from './api.js';

vi.mock('./api.js', () => ({ api: vi.fn() }));
beforeEach(() => { api.mockReset(); api.mockResolvedValue({ usuario: null }); });
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

test('el instructor conserva su pantalla provisional y puede cerrar sesión', async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Ingresar o registrarse' }));
  fireEvent.change(screen.getByLabelText('CI'), { target: { value: '1234' } });
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave' } });
  api.mockImplementation(async (ruta) => ruta === 'login'
    ? { usuario: { nombre_usuario: 'Ana', rol: 'instructor', rol_nombre: 'Instructor' } } : { usuario: null });
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }));
  await screen.findByText('Hola, Ana.');
  expect(screen.queryByRole('heading', { name: 'Próximos talleres' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar sesión' }));
  await screen.findByRole('button', { name: 'Ingresar o registrarse' });
  expect(api).toHaveBeenCalledWith('logout', {});
});

test('el participante llega al catálogo vacío después de iniciar sesión', async () => {
  const catalogo = { talleres: [], zona_horaria: 'UTC', usuario: { nombre: 'Ismael' } };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => catalogo }));
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Ingresar o registrarse' }));
  fireEvent.change(screen.getByLabelText('CI'), { target: { value: '1234' } });
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave' } });
  api.mockImplementation(async (ruta) => ruta === 'login'
    ? { usuario: { nombre_usuario: 'Ismael', rol: 'participante', rol_nombre: 'Participante' } } : { usuario: null });
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }));
  await screen.findByRole('heading', { name: 'No hay talleres disponibles' });
  expect(screen.getByText('Ismael')).toBeTruthy();
});

test('un rechazo del servidor se muestra sin abrir la cuenta', async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Ingresar o registrarse' }));
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
});
