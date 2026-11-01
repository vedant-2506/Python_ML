
function ensureAuth() {
  if (!localStorage.getItem('rankresume_token')) {
    location.href = 'login.html';
    return false;
  }
  return true;
}

function logout() {
  localStorage.removeItem('rankresume_token');
  localStorage.removeItem('rankresume_user');
  location.href = 'login.html';
}

function showMessage(message, type = 'danger') {
  if (window.UI?.toast) {
    UI.toast(message, type);
  } else {
    alert(message);
  }
}

function getErrorMessage(error) {
  try {
    const data = JSON.parse(error.message);
    return data.detail || data.message || error.message;
  } catch {
    return error.message || 'Something went wrong. Please try again.';
  }
}

async function bindAuthForm(form, type) {
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }

    const button = form.querySelector('button[type="submit"]')
      || form.querySelector('button:not([type])');

    const originalText = button?.textContent.trim() || 'Submit';

    try {
      if (button) {
        button.disabled = true;
        button.textContent = 'Please wait...';
      }

      const baseURL =
        window.RankResumeConfig?.API_BASE_URL || 'http://127.0.0.1:8000';

      let endpoint;
      let payload;

      if (type === 'signup') {
        endpoint = '/api/auth/signup';

        payload = {
          company_name:
            form.querySelector('[name="company_name"]')?.value.trim()
            || form.querySelector('[name="company"]')?.value.trim()
            || '',
          email: form.querySelector('[name="email"]').value.trim(),
          password: form.querySelector('[name="password"]').value
        };

        if (!payload.company_name) {
          throw new Error('Please enter your company name.');
        }
      } else {
        endpoint = '/api/auth/login';

        payload = {
          email: form.querySelector('[name="email"]').value.trim(),
          password: form.querySelector('[name="password"]').value
        };
      }

      const response = await fetch(baseURL + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.detail || data.message || `Request failed (${response.status})`);
      }

      if (type === 'signup') {
        form.innerHTML = `
          <div class="text-center py-4">
            <i class="bi bi-envelope-check text-success fs-1"></i>
            <h3 class="mt-3">Verify your email</h3>
            <p class="text-muted">
              Your account has been created. Open the verification link
              sent to your email before logging in.
            </p>
            <a class="btn btn-primary" href="login.html">Back to login</a>
          </div>
        `;
        showMessage('Account created. Please verify your email.', 'success');
        return;
      }

      if (!data.token) {
        throw new Error('The server did not return an authentication token.');
      }

      localStorage.setItem('rankresume_token', data.token);
      localStorage.setItem('rankresume_user', JSON.stringify(data.user || {}));

      location.href = 'dashboard.html';

    } catch (error) {
      showMessage(getErrorMessage(error));
    } finally {
      if (button && button.isConnected) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  });
}

async function handleEmailVerification() {
  const params = new URLSearchParams(location.search);
  const token = params.get('verify');

  if (!token) return;

  const baseURL =
    window.RankResumeConfig?.API_BASE_URL || 'http://127.0.0.1:8000';

  try {
    const response = await fetch(
      `${baseURL}/api/auth/verify-email?token=${encodeURIComponent(token)}`
    );

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || 'Email verification failed.');
    }

    showMessage('Email verified successfully. You can now log in.', 'success');
  } catch (error) {
    showMessage(getErrorMessage(error));
  } finally {
    // Remove the verification token from the visible URL.
    history.replaceState({}, document.title, location.pathname);
  }
}

window.Auth = {
  ensureAuth,
  logout,
  bindAuthForm
};

document.addEventListener('DOMContentLoaded', handleEmailVerification);
