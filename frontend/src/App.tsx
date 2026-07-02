import { Route, Routes } from "react-router-dom";

import { Home } from "./pages/Home";
import { NotFound } from "./pages/NotFound";
import { Profile } from "./pages/Profile";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/profile" element={<Profile />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
