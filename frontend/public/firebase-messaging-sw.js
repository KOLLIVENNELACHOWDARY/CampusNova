/* Shows push notifications while the site is closed. Configuration is passed in the query string by the app
   registration (service workers cannot read Vite env vars), so this file contains no secrets. */
importScripts('https://www.gstatic.com/firebasejs/11.0.2/firebase-app-compat.js')
importScripts('https://www.gstatic.com/firebasejs/11.0.2/firebase-messaging-compat.js')

const params = new URL(self.location).searchParams
if (params.get('apiKey')) {
  firebase.initializeApp({
    apiKey: params.get('apiKey'), projectId: params.get('projectId'),
    messagingSenderId: params.get('messagingSenderId'), appId: params.get('appId'),
  })
  const messaging = firebase.messaging()
  messaging.onBackgroundMessage((payload) => {
    const { title, body } = payload.notification || {}
    self.registration.showNotification(title || 'CampusNova', { body, data: payload.data })
  })
}
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(clients.openWindow('/complaints'))
})
