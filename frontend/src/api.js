let csrfToken;

export async function solicitudApi(url, { method = 'GET', datos, signal } = {}) {
  const response = await fetch(url, {
    method,
    signal,
    credentials: 'same-origin',
    headers: datos === undefined ? {} : {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken || '',
    },
    ...(datos === undefined ? {} : { body: JSON.stringify(datos) }),
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error('El servidor no respondió correctamente. Comprueba que Django esté iniciado.');
  }
  if (result.csrfToken) csrfToken = result.csrfToken;
  if (!response.ok) {
    const messages = Object.values(result.errores || {}).flat();
    const error = new Error(result.mensaje || result.detail || messages.join(' ') || 'No se pudo completar la solicitud.');
    error.status = response.status;
    throw error;
  }
  return result;
}
