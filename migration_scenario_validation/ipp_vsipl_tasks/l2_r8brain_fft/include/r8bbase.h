/*
 * Trimmed subset of r8brain-free-src's r8bbase.h.
 *
 * The extraction only needs the helpers that the real-valued FFT component
 * actually uses: the fixed-capacity buffer (for the IPP specification and work
 * buffers), the bit-occupancy helper and the FIR response / group-delay pair
 * that calcMinPhaseTransform() reports.  The rest of r8bbase.h (filters,
 * interpolators, splines, caches) belongs to the resampler and is not part of
 * this component.  The code is unchanged.
 *
 * r8brain-free-src Copyright (c) 2013-2026 Aleksey Vaneev
 * See the "LICENSE" file for license.
 */

#ifndef R8BBASE_INCLUDED
#define R8BBASE_INCLUDED

#define R8B_VERSION "7.7"

#include <cstring>
#include <cmath>
#include <new>
#include <cstdint>

#define R8B_CONST constexpr
#define R8B_NULL nullptr

#define R8BASSERT( e ) (void) 0

#define R8BNOCTOR( ClassName ) \
	public: \
		ClassName( const ClassName& ) = delete; \
		ClassName& operator = ( const ClassName& ) = delete;

namespace r8b {

using std :: memcpy;
using std :: memset;
using std :: floor;
using std :: ceil;
using std :: fabs;
using std :: sqrt;
using std :: log;
using std :: exp;
using std :: pow;
using std :: sin;
using std :: cos;
using std :: atan2;
using std :: size_t;
using std :: uintptr_t;

R8B_CONST double R8B_PI = 3.14159265358979324; ///< Equals `pi`.
R8B_CONST double R8B_2PI = 6.28318530717958648; ///< Equals `2*pi`.

/** @brief The default base class for objects created on heap. */
class CStdClassAllocator
{
};

/** @brief Memory buffer allocator that uses standard C++ "new". */
class CStdMemAllocator : public CStdClassAllocator
{
public:
	static void* allocmem( const size_t Size )
	{
		return( new char[ Size ]);
	}

	static void freemem( void* const p )
	{
		delete[] (char*) p;
	}
};

/** @brief Forces `ptr` to be aligned to `align` bytes (power of 2). */
template< typename T >
inline T* align_ptr( T* const ptr, const uintptr_t align )
{
	return( (T*) (( (uintptr_t) ptr + align - 1 ) & ~( align - 1 )));
}

/** @brief Placement-new over a raw block (see CFixedBuffer). */
template< typename T >
inline T* construct_ptr( void* const ptr, const size_t c )
{
	return( :: new( ptr ) T[ c ]);
}

/**
 * @brief Templated memory buffer class for element buffers of fixed capacity.
 *
 * 64-byte aligned, always heap allocated (so the object itself can be moved).
 */

template< typename T >
class CFixedBuffer : protected CStdMemAllocator
{
	R8BNOCTOR( CFixedBuffer )

public:
	CFixedBuffer()
		: Data0( R8B_NULL )
		, Data( R8B_NULL )
	{
	}

	CFixedBuffer( const int Capacity )
	{
		R8BASSERT( Capacity >= 0 );

		Data0 = allocmem( (size_t) Capacity * sizeof( T ) + Alignment );
		Data = construct_ptr< T >( align_ptr( Data0, Alignment ),
			(size_t) Capacity );

		R8BASSERT( Data0 != R8B_NULL || Capacity == 0 );
	}

	~CFixedBuffer()
	{
		freemem( Data0 );
	}

	void alloc( const int Capacity )
	{
		R8BASSERT( Capacity >= 0 );

		freemem( Data0 );
		Data0 = allocmem( (size_t) Capacity * sizeof( T ) + Alignment );
		Data = construct_ptr< T >( align_ptr( Data0, Alignment ),
			(size_t) Capacity );

		R8BASSERT( Data0 != R8B_NULL || Capacity == 0 );
	}

	void realloc( const int PrevCapacity, const int NewCapacity )
	{
		R8BASSERT( PrevCapacity >= 0 );
		R8BASSERT( NewCapacity >= 0 );

		void* const NewData0 = allocmem( (size_t) NewCapacity * sizeof( T ) +
			Alignment );

		T* const NewData = construct_ptr< T >( align_ptr( NewData0,
			Alignment ), (size_t) NewCapacity );

		const size_t CopySize = ( PrevCapacity > NewCapacity ?
			(size_t) NewCapacity : (size_t) PrevCapacity ) * sizeof( T );

		if( CopySize > 0 )
		{
			memcpy( NewData, Data, CopySize );
		}

		freemem( Data0 );
		Data0 = NewData0;
		Data = NewData;

		R8BASSERT( Data0 != R8B_NULL || NewCapacity == 0 );
	}

	void moveFrom( CFixedBuffer& s )
	{
		freemem( Data0 );
		Data0 = s.Data0;
		Data = s.Data;
		s.Data0 = R8B_NULL;
		s.Data = R8B_NULL;
	}

	void free()
	{
		freemem( Data0 );
		Data0 = R8B_NULL;
		Data = R8B_NULL;
	}

	operator T* () const
	{
		return( Data );
	}

private:
	static const size_t Alignment = 64;
	void* Data0;
	T* Data;
};

/**
 * @brief Calculate the exact number of bits a value needs for representation.
 */

inline int getBitOccupancy( const int v )
{
	static const unsigned char OccupancyTable[] =
	{
		1, 1, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4,
		5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
		6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
		6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
		7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
		7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
		7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
		7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
		8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8
	};

	const int tt = v >> 16;

	if( tt != 0 )
	{
		const int t = v >> 24;

		return( t != 0 ? 24 + OccupancyTable[ t & 0xFF ] :
			16 + OccupancyTable[ tt ]);
	}
	else
	{
		const int t = v >> 8;

		return( t != 0 ? 8 + OccupancyTable[ t ] : OccupancyTable[ v ]);
	}
}

/**
 * @brief FIR filter's frequency response calculation.
 */

inline void calcFIRFilterResponse( const double* flt, int fltlen,
	const double th, double& re0, double& im0, const int fltlat = 0 )
{
	const double sincr = 2.0 * cos( th );
	double cvalue1;
	double svalue1;

	if( fltlat == 0 )
	{
		cvalue1 = 1.0;
		svalue1 = 0.0;
	}
	else
	{
		cvalue1 = cos( -fltlat * th );
		svalue1 = sin( -fltlat * th );
	}

	double cvalue2 = cos( -( fltlat + 1 ) * th );
	double svalue2 = sin( -( fltlat + 1 ) * th );

	double re = 0.0;
	double im = 0.0;

	while( fltlen > 0 )
	{
		re += cvalue1 * flt[ 0 ];
		im += svalue1 * flt[ 0 ];
		flt++;
		fltlen--;

		double tmp = cvalue1;
		cvalue1 = sincr * cvalue1 - cvalue2;
		cvalue2 = tmp;

		tmp = svalue1;
		svalue1 = sincr * svalue1 - svalue2;
		svalue2 = tmp;
	}

	re0 = re;
	im0 = im;
}

/**
 * @brief FIR filter's group delay calculation function.
 */

inline double calcFIRFilterGroupDelay( const double* const flt,
	const int fltlen, const double th )
{
	const int Count = 2;
	const double thd2 = 1e-9;
	double ths[ Count ] = { th - thd2, th + thd2 };

	if( ths[ 0 ] < 0.0 )
	{
		ths[ 0 ] = 0.0;
	}

	if( ths[ 1 ] > R8B_PI )
	{
		ths[ 1 ] = R8B_PI;
	}

	double ph1[ Count ];
	int i;

	for( i = 0; i < Count; i++ )
	{
		double re1;
		double im1;

		calcFIRFilterResponse( flt, fltlen, ths[ i ], re1, im1 );
		ph1[ i ] = atan2( im1, re1 );
	}

	if( fabs( ph1[ 1 ] - ph1[ 0 ]) > R8B_PI )
	{
		if( ph1[ 1 ] > ph1[ 0 ])
		{
			ph1[ 1 ] -= R8B_2PI;
		}
		else
		{
			ph1[ 1 ] += R8B_2PI;
		}
	}

	const double thd = ths[ 1 ] - ths[ 0 ];

	return(( ph1[ 1 ] - ph1[ 0 ]) / thd );
}

} // namespace r8b

/* Normally set in r8bconf.h; the default is the class allocator above. */
#ifndef R8B_BASECLASS
	#define R8B_BASECLASS :: r8b :: CStdClassAllocator
#endif

#endif // R8BBASE_INCLUDED