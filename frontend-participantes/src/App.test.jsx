import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App.jsx';

const respuesta = {
  usuario: { nombre: 'Ismael' },
  zona_horaria: 'America/La_Paz',
  talleres: [{ codigo: 'T-001', nombre: 'Introducción a Python', descripcion: 'Desde cero.', cupos: 5, fecha_inicio: '2026-10-20T14:00:00Z', fecha_fin: '2026-10-20T16:00:00Z' }],
};

afterEach(() => vi.unstubAllGlobals());

describe('Catálogo del participante', () => {
  it('muestra carga y después consulta la API con sesión y presenta el taller', async () => {
    let completar;
    const fetchMock = vi.fn(() => new Promise((resolve) => { completar = resolve; }));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(screen.getByRole('status')).toHaveTextContent('Cargando talleres');
    completar({ ok: true, json: async () => respuesta });
    expect(await screen.findByRole('heading', { name: 'Introducción a Python' })).toBeInTheDocument();
    expect(screen.getByText('5 personas')).toBeInTheDocument();
    expect(screen.getByText('Ismael')).toBeInTheDocument();
    expect(screen.getByText('Horarios en America/La_Paz')).toBeInTheDocument();
    expect(screen.getByText(/10:00/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/participantes/talleres/', expect.objectContaining({ credentials: 'same-origin', signal: expect.any(AbortSignal) }));
  });

  it('muestra el estado vacío cuando la API no devuelve talleres', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...respuesta, talleres: [] }) }));
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'No hay talleres disponibles' })).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it('permite reintentar después de un error de red', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({ ok: true, json: async () => respuesta });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No pudimos cargar');
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByRole('heading', { name: 'Introducción a Python' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('presenta acceso al login cuando la API responde 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    render(<App />);
    const enlace = await screen.findByRole('link', { name: 'Ir a iniciar sesión' });
    expect(enlace).toHaveAttribute('href', '/cuentas/login/?next=%2Ftalleres%2F');
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it('no interpreta el nombre como HTML ni muestra avisos por descripción vacía', async () => {
    const datos = { ...respuesta, talleres: [{ ...respuesta.talleres[0], nombre: '<img src=x onerror=alert(1)>', descripcion: '' }] };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => datos }));
    render(<App />);
    expect(await screen.findByRole('heading', { name: '<img src=x onerror=alert(1)>' })).toBeInTheDocument();
    expect(screen.queryByText(/todavía no tiene una descripción/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('article').querySelector('img')).toBeNull());
  });
});
