import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'

import { App } from './App'
import { AuthProvider } from './lib/auth'
// Шрифты — из сборки, а не с Google: без внешнего запроса, блокирующего отрисовку, и школьные фильтры их не режут.
import '@fontsource/geologica/500.css'
import '@fontsource/geologica/600.css'
import '@fontsource/geologica/700.css'
import '@fontsource/golos-text/400.css'
import '@fontsource/golos-text/500.css'
import '@fontsource/golos-text/600.css'
import '@fontsource/golos-text/700.css'
import './styles.css'

const router = createBrowserRouter([{ path: '*', element: <AuthProvider><App /></AuthProvider> }])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
