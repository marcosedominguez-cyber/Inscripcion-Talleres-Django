import { solicitudApi } from '../api.js';

export async function obtenerCatalogo({ signal } = {}) {
  const response = await fetch('/api/participantes/talleres/', {
    signal,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  });

  if (!response.ok) {
    const error = new Error('No pudimos cargar los talleres. Intentá nuevamente.');
    error.status = response.status;
    throw error;
  }

  const data = await response.json();
  if (!Array.isArray(data.talleres) || typeof data.zona_horaria !== 'string') {
    throw new Error('La respuesta del catálogo no tiene el formato esperado.');
  }
  return data;
}

export async function obtenerMisInscripciones({ signal } = {}) {
  const data = await solicitudApi('/api/participantes/inscripciones/', { signal });
  if (!Array.isArray(data.inscripciones) || typeof data.zona_horaria !== 'string') {
    throw new Error('La respuesta de tus inscripciones no tiene el formato esperado.');
  }
  return data;
}


export function inscribirEnTaller(codigoTaller) {
  return solicitudApi('/api/participantes/inscripciones/', {
    method: 'POST', datos: { codigo_taller: codigoTaller },
  });
}


export function solicitarEspera(codigoTaller) {
  return solicitudApi('/api/participantes/espera/', {
    method: 'POST', datos: { codigo_taller: codigoTaller },
  });
}


export function cancelarInscripcion(codigoTaller) {
  return solicitudApi('/api/participantes/inscripciones/cancelar/', {
    method: 'POST', datos: { codigo_taller: codigoTaller },
  });
}
