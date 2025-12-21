"use client";

import { Suspense, createContext, Dispatch, ReactNode, SetStateAction } from "react";

import { useSignInModal } from "@/components/modals//sign-in-modal";

export const ModalContext = createContext<{
  setShowSignInModal: Dispatch<SetStateAction<boolean>>;
}>({
  setShowSignInModal: () => {},
});

export default function ModalProvider({ children }: { children: ReactNode }) {
  const { SignInModal, setShowSignInModal } = useSignInModal();

  return (
    <ModalContext.Provider
      value={{
        setShowSignInModal,
      }}
    >
      {/* Next.js requires useSearchParams() to be under a Suspense boundary */}
      <Suspense fallback={null}>
        <SignInModal />
      </Suspense>
      {children}
    </ModalContext.Provider>
  );
}
