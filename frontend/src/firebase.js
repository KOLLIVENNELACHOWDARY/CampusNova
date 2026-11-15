// Optional Firebase integration (Google sign-in + web push). Everything is off unless VITE_FIREBASE_* are set,
// and the Firebase SDK is only downloaded when it is used (dynamic import), so the normal app stays small.
const cfg = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}
export const VAPID_KEY = import.meta.env.VITE_FIREBASE_VAPID_KEY

export const firebaseConfigured = () => Boolean(cfg.apiKey && cfg.projectId && cfg.appId)

async function getApp() {
  const { initializeApp, getApps } = await import('firebase/app')
  return getApps()[0] || initializeApp(cfg)
}

/** Opens the Google sign-in popup and returns the Firebase ID token to send to POST /auth/firebase. */
export async function googleIdToken() {
  const { getAuth, GoogleAuthProvider, signInWithPopup } = await import('firebase/auth')
  const result = await signInWithPopup(getAuth(await getApp()), new GoogleAuthProvider())
  return result.user.getIdToken()
}

/** Asks for notification permission and returns this browser's FCM token (or throws a readable Error). */
export async function pushToken() {
  if (!firebaseConfigured() || !VAPID_KEY) throw new Error('Push notifications are not configured for this site.')
  if (!('serviceWorker' in navigator) || !('Notification' in window)) throw new Error('This browser does not support push notifications.')
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('Notifications are blocked in the browser settings.')
  const { getMessaging, getToken } = await import('firebase/messaging')
  const q = new URLSearchParams({ apiKey: cfg.apiKey, projectId: cfg.projectId, messagingSenderId: cfg.messagingSenderId || '', appId: cfg.appId })
  const registration = await navigator.serviceWorker.register(`/firebase-messaging-sw.js?${q}`)
  const token = await getToken(getMessaging(await getApp()), { vapidKey: VAPID_KEY, serviceWorkerRegistration: registration })
  if (!token) throw new Error('Could not get a push token.')
  return token
}
