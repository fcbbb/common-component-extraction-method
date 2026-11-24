#ifndef THR_H
#define THR_H

#include <stddef.h>

/*
 * Public threading surface of the runtime.
 *
 * Every object is caller-allocated storage that the backend initialises in
 * place.  Calls return THR_OK or one of the THR_* codes below; the codes are
 * the public contract and are deliberately not errno values.
 *
 * Thread identities are values: creation stores one in the caller's variable,
 * the identity stays valid until join, and join both waits for the thread and
 * releases its resources.
 */

typedef unsigned long thr_thread_t;

enum {
    THR_OK = 0,
    THR_BUSY = 1,
    THR_AGAIN = 2,
    THR_TIMEDOUT = 3,
    THR_INVAL = 4,
    THR_NOMEM = 5,
    THR_NOSYS = 6
};

#define THR_CPU_WORDS 16u  /* the affinity mask is 1024 unsigned long bits */

typedef struct thr_mutex { unsigned long opaque[12]; } thr_mutex_t;
typedef struct thr_rwlock { unsigned long opaque[12]; } thr_rwlock_t;
typedef struct thr_sem { unsigned long opaque[12]; } thr_sem_t;
typedef struct thr_cond { unsigned long opaque[12]; } thr_cond_t;
typedef struct thr_once { unsigned long opaque[2]; } thr_once_t;

/* The guard is usable as a static initialiser; the backend maps it to the
 * platform's native one-time initialiser. */
#define THR_ONCE_INIT {{0UL, 0UL}}

typedef int thr_tls_key_t;

int thr_thread_create(thr_thread_t *thread, void *(*entry)(void *), void *arg,
                      size_t stack_size);
int thr_thread_join(thr_thread_t *thread);
thr_thread_t thr_thread_self(void);
int thr_thread_equal(thr_thread_t a, thr_thread_t b);

int thr_mutex_init(thr_mutex_t *mutex);
int thr_mutex_init_recursive(thr_mutex_t *mutex);
int thr_mutex_lock(thr_mutex_t *mutex);
int thr_mutex_trylock(thr_mutex_t *mutex);
int thr_mutex_unlock(thr_mutex_t *mutex);
int thr_mutex_destroy(thr_mutex_t *mutex);

int thr_rwlock_init(thr_rwlock_t *lock);
int thr_rwlock_rdlock(thr_rwlock_t *lock);
int thr_rwlock_wrlock(thr_rwlock_t *lock);
int thr_rwlock_tryrdlock(thr_rwlock_t *lock);
int thr_rwlock_trywrlock(thr_rwlock_t *lock);
int thr_rwlock_unlock(thr_rwlock_t *lock);
int thr_rwlock_destroy(thr_rwlock_t *lock);

int thr_sem_init(thr_sem_t *sem, unsigned int count);
int thr_sem_post(thr_sem_t *sem);
int thr_sem_wait(thr_sem_t *sem);
int thr_sem_trywait(thr_sem_t *sem);
int thr_sem_destroy(thr_sem_t *sem);

int thr_cond_init(thr_cond_t *cond);
int thr_cond_wait(thr_cond_t *cond, thr_mutex_t *mutex);
int thr_cond_timedwait(thr_cond_t *cond, thr_mutex_t *mutex,
                       unsigned long milliseconds);
int thr_cond_signal(thr_cond_t *cond);
int thr_cond_broadcast(thr_cond_t *cond);
int thr_cond_destroy(thr_cond_t *cond);

int thr_tls_create(thr_tls_key_t *key, void (*destructor)(void *));
void *thr_tls_get(thr_tls_key_t key);
int thr_tls_set(thr_tls_key_t key, void *value);
int thr_tls_delete(thr_tls_key_t key);

int thr_once(thr_once_t *guard, void (*callback)(void));

/* Affinity masks are arrays of THR_CPU_WORDS unsigned longs, bit i denoting
 * logical CPU i.  A smaller buffer is invalid.  Requesting a mask with no CPU
 * set, or one the target cannot apply, is invalid as well. */
int thr_affinity_set(const unsigned long *mask, unsigned int words);
int thr_affinity_get(unsigned long *mask, unsigned int words);
int thr_affinity_current(void);

#endif /* THR_H */