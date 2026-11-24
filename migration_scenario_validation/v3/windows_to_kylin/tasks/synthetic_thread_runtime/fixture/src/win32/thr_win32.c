/*
 * Windows reference backend for the runtime's threading surface.
 *
 * This file documents how the surface is expressed on Win32: kernel handles
 * for threads and semaphores, critical sections for plain and recursive
 * mutexes, SRW locks for readers/writers, condition variables, fibre-local
 * storage for TLS, and an affinity mask over SetThreadAffinityMask.  It is
 * not built on the target platform; src/posix/thr_posix.c is what the port
 * must produce.
 */
#define WIN32_LEAN_AND_MEAN
#include "thr.h"

#include <windows.h>

/* The public storage is pointer-sized on the Windows side. */
#define CS(m) ((CRITICAL_SECTION *)(void *)(m))
#define SRW(l) ((SRWLOCK *)(void *)(l))
#define SEMH(s) (*(HANDLE *)(void *)(s))
#define CONDV(c) ((CONDITION_VARIABLE *)(void *)(c))
#define ONCEG(o) ((INIT_ONCE *)(void *)(o))

int thr_thread_create(thr_thread_t *thread, void *(*entry)(void *), void *arg,
                      size_t stack_size)
{
    HANDLE handle;

    if (!thread || !entry) {
        return THR_INVAL;
    }
    handle = CreateThread(NULL, (SIZE_T)stack_size,
                          (LPTHREAD_START_ROUTINE)entry, arg, 0, NULL);
    if (!handle) {
        return THR_INVAL;
    }
    *thread = (thr_thread_t)(ULONG_PTR)handle;
    return THR_OK;
}

int thr_thread_join(thr_thread_t *thread)
{
    HANDLE handle;

    if (!thread || *thread == 0) {
        return THR_INVAL;
    }
    handle = (HANDLE)(ULONG_PTR)*thread;
    if (WaitForSingleObject(handle, INFINITE) != WAIT_OBJECT_0) {
        return THR_INVAL;
    }
    CloseHandle(handle);
    *thread = 0;
    return THR_OK;
}

thr_thread_t thr_thread_self(void)
{
    return (thr_thread_t)GetCurrentThreadId();
}

int thr_thread_equal(thr_thread_t a, thr_thread_t b)
{
    return a == b ? 1 : 0;
}

int thr_mutex_init(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    InitializeCriticalSection(CS(mutex));
    return THR_OK;
}

int thr_mutex_init_recursive(thr_mutex_t *mutex)
{
    /* A critical section is recursive; the distinction the target needs does
     * not exist here, so both initialisers do the same thing. */
    return thr_mutex_init(mutex);
}

int thr_mutex_lock(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    EnterCriticalSection(CS(mutex));
    return THR_OK;
}

int thr_mutex_trylock(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    return TryEnterCriticalSection(CS(mutex)) ? THR_OK : THR_BUSY;
}

int thr_mutex_unlock(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    LeaveCriticalSection(CS(mutex));
    return THR_OK;
}

int thr_mutex_destroy(thr_mutex_t *mutex)
{
    if (!mutex) {
        return THR_INVAL;
    }
    DeleteCriticalSection(CS(mutex));
    return THR_OK;
}

int thr_rwlock_init(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    InitializeSRWLock(SRW(lock));
    return THR_OK;
}

int thr_rwlock_rdlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    AcquireSRWLockShared(SRW(lock));
    return THR_OK;
}

int thr_rwlock_wrlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    AcquireSRWLockExclusive(SRW(lock));
    return THR_OK;
}

int thr_rwlock_tryrdlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return TryAcquireSRWLockShared(SRW(lock)) ? THR_OK : THR_BUSY;
}

int thr_rwlock_trywrlock(thr_rwlock_t *lock)
{
    if (!lock) {
        return THR_INVAL;
    }
    return TryAcquireSRWLockExclusive(SRW(lock)) ? THR_OK : THR_BUSY;
}

int thr_rwlock_unlock(thr_rwlock_t *lock)
{
    /* SRW locks do not record whether the holder is a reader or a writer. */
    if (!lock) {
        return THR_INVAL;
    }
    ReleaseSRWLockExclusive(SRW(lock));
    return THR_OK;
}

int thr_rwlock_destroy(thr_rwlock_t *lock)
{
    (void)lock;
    return THR_OK;
}

int thr_sem_init(thr_sem_t *sem, unsigned int count)
{
    HANDLE handle;

    if (!sem || count > 0x7fffffffu) {
        return THR_INVAL;
    }
    handle = CreateSemaphoreA(NULL, (LONG)count, 0x7fffffffL, NULL);
    if (!handle) {
        return THR_INVAL;
    }
    SEMH(sem) = handle;
    return THR_OK;
}

int thr_sem_post(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    return ReleaseSemaphore(SEMH(sem), 1, NULL) ? THR_OK : THR_INVAL;
}

int thr_sem_wait(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    return WaitForSingleObject(SEMH(sem), INFINITE) == WAIT_OBJECT_0
               ? THR_OK
               : THR_INVAL;
}

int thr_sem_trywait(thr_sem_t *sem)
{
    DWORD rc;

    if (!sem) {
        return THR_INVAL;
    }
    rc = WaitForSingleObject(SEMH(sem), 0);
    if (rc == WAIT_OBJECT_0) {
        return THR_OK;
    }
    return rc == WAIT_TIMEOUT ? THR_AGAIN : THR_INVAL;
}

int thr_sem_destroy(thr_sem_t *sem)
{
    if (!sem) {
        return THR_INVAL;
    }
    CloseHandle(SEMH(sem));
    SEMH(sem) = NULL;
    return THR_OK;
}

int thr_cond_init(thr_cond_t *cond)
{
    if (!cond) {
        return THR_INVAL;
    }
    InitializeConditionVariable(CONDV(cond));
    return THR_OK;
}

int thr_cond_wait(thr_cond_t *cond, thr_mutex_t *mutex)
{
    if (!cond || !mutex) {
        return THR_INVAL;
    }
    return SleepConditionVariableCS(CONDV(cond), CS(mutex), INFINITE)
               ? THR_OK
               : THR_INVAL;
}

int thr_cond_timedwait(thr_cond_t *cond, thr_mutex_t *mutex,
                       unsigned long milliseconds)
{
    DWORD rc;

    if (!cond || !mutex) {
        return THR_INVAL;
    }
    rc = SleepConditionVariableCS(CONDV(cond), CS(mutex),
                                  (DWORD)milliseconds);
    if (rc) {
        return THR_OK;
    }
    return GetLastError() == ERROR_TIMEOUT ? THR_TIMEDOUT : THR_INVAL;
}

int thr_cond_signal(thr_cond_t *cond)
{
    if (!cond) {
        return THR_INVAL;
    }
    WakeConditionVariable(CONDV(cond));
    return THR_OK;
}

int thr_cond_broadcast(thr_cond_t *cond)
{
    if (!cond) {
        return THR_INVAL;
    }
    WakeAllConditionVariable(CONDV(cond));
    return THR_OK;
}

int thr_cond_destroy(thr_cond_t *cond)
{
    (void)cond;
    return cond ? THR_OK : THR_INVAL;
}

int thr_tls_create(thr_tls_key_t *key, void (*destructor)(void *))
{
    DWORD slot;

    if (!key) {
        return THR_INVAL;
    }
    slot = FlsAlloc((PFLS_CALLBACK_FUNCTION)destructor);
    if (slot == FLS_OUT_OF_INDEXES) {
        return THR_NOMEM;
    }
    *key = (thr_tls_key_t)slot;
    return THR_OK;
}

void *thr_tls_get(thr_tls_key_t key)
{
    return FlsGetValue((DWORD)key);
}

int thr_tls_set(thr_tls_key_t key, void *value)
{
    return FlsSetValue((DWORD)key, value) ? THR_OK : THR_INVAL;
}

int thr_tls_delete(thr_tls_key_t key)
{
    return FlsFree((DWORD)key) ? THR_OK : THR_INVAL;
}

static BOOL CALLBACK once_callback(PINIT_ONCE once, PVOID parameter,
                                   PVOID *context)
{
    (void)once;
    (void)context;
    ((void (*)(void))parameter)();
    return TRUE;
}

int thr_once(thr_once_t *guard, void (*callback)(void))
{
    if (!guard || !callback) {
        return THR_INVAL;
    }
    return InitOnceExecuteOnce(ONCEG(guard), once_callback, (PVOID)callback,
                               NULL)
               ? THR_OK
               : THR_INVAL;
}

int thr_affinity_set(const unsigned long *mask, unsigned int words)
{
    DWORD_PTR value = 0;
    unsigned int i;

    if (!mask || words < THR_CPU_WORDS) {
        return THR_INVAL;
    }
    for (i = 0; i < (THR_CPU_WORDS < 8u ? THR_CPU_WORDS : 8u); i++) {
        value |= (DWORD_PTR)mask[i] << (i * 8u);
    }
    if (value == 0) {
        return THR_INVAL;
    }
    return SetThreadAffinityMask(GetCurrentThread(), value) ? THR_OK
                                                            : THR_INVAL;
}

int thr_affinity_get(unsigned long *mask, unsigned int words)
{
    DWORD_PTR value;
    unsigned int i;

    if (!mask || words < THR_CPU_WORDS) {
        return THR_INVAL;
    }
    value = SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)-1);
    if (value == 0) {
        return THR_INVAL;
    }
    SetThreadAffinityMask(GetCurrentThread(), value);
    for (i = 0; i < THR_CPU_WORDS; i++) {
        mask[i] = i < 8u ? (unsigned long)((value >> (i * 8u)) & 0xffu) : 0UL;
    }
    return THR_OK;
}

int thr_affinity_current(void)
{
    return (int)GetCurrentProcessorNumber();
}