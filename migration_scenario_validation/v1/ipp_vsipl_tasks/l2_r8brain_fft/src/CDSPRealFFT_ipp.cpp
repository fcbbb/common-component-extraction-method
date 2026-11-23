/**
 * @file CDSPRealFFT_ipp.cpp
 *
 * @brief Real-valued FFT transform class (Intel IPP backend).
 *
 * Extracted from r8brain-free-src's CDSPRealFFT.h (the R8B_IPP=1 branch).
 * Only the IPP branch is reproduced: the PFFFT, PFFFT DOUBLE and Ooura
 * branches are gone, and the backend state that the upstream class keeps as
 * data members is defined here as an opaque struct so the header stays free
 * of IPP types.
 *
 * IPP is initialised with IPP_FFT_NODIV_BY_ANY on both sides, and the blocks
 * use IPP's "Perm" real-FFT layout.  The five IPP entry points used are
 * ippsFFTGetSize_R_64f, ippsFFTInit_R_64f, ippsFFTFwd_RToPerm_64f,
 * ippsFFTInv_PermToR_64f and ippsMulPerm_64f.
 *
 * The upstream keeper keeps its FFT objects in a static singly-linked list;
 * the same pool is reproduced here with a std::map plus a std::mutex.  The
 * objects are still never destroyed and are handed out again on the next
 * request of the same length.
 *
 * r8brain-free-src Copyright (c) 2013-2026 Aleksey Vaneev
 *
 * See the "LICENSE" file for license.
 */

#include "CDSPRealFFT.h"

#include <ipp.h>

#include <map>
#include <mutex>
#include <vector>

namespace r8b {

struct CDSPRealFFTSetup :: Spec
{
	IppsFFTSpec_R_64f* SpecPtr; ///< Initialized IPP specification.
	CFixedBuffer< unsigned char > SpecBuffer; ///< Specification buffer.
	int WorkBufferSize; ///< Size of the per-transform work buffer.
};

struct CDSPRealFFT :: Work
{
	CFixedBuffer< unsigned char > WorkBuffer; ///< IPP work buffer.
};

CDSPRealFFTSetup :: CDSPRealFFTSetup( const int aLenBits )
	: LenBits( aLenBits )
	, Len( 1 << aLenBits )
	, InvMulConst( 1.0 / Len )
	, spec( new Spec() )
{
	int SpecBufferSize;
	int InitBufferSize;

	ippsFFTGetSize_R_64f( LenBits, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
		&SpecBufferSize, &InitBufferSize, &spec -> WorkBufferSize );

	CFixedBuffer< unsigned char > InitBuffer( InitBufferSize );
	spec -> SpecBuffer.alloc( SpecBufferSize );

	ippsFFTInit_R_64f( &spec -> SpecPtr, LenBits, IPP_FFT_NODIV_BY_ANY,
		ippAlgHintFast, spec -> SpecBuffer, InitBuffer );
}

CDSPRealFFTSetup :: ~CDSPRealFFTSetup()
{
	delete spec;
}

CDSPRealFFT :: CDSPRealFFT( const CDSPRealFFTSetup* const s0 )
	: s( s0 )
	, Len( s -> Len )
	, work( new Work() )
{
	work -> WorkBuffer.alloc( s -> spec -> WorkBufferSize );
}

CDSPRealFFT :: ~CDSPRealFFT()
{
	delete work;
}

realfft_t* CDSPRealFFT :: forward( double* const p ) const
{
	ippsFFTFwd_RToPerm_64f( p, p, s -> spec -> SpecPtr, work -> WorkBuffer );

	return( p );
}

void CDSPRealFFT :: inverse( realfft_t* const p ) const
{
	ippsFFTInv_PermToR_64f( p, p, s -> spec -> SpecPtr, work -> WorkBuffer );
}

void CDSPRealFFT :: multiplyBlocks( const realfft_t* const ip1,
	const realfft_t* const ip2, realfft_t* const op ) const
{
	ippsMulPerm_64f( (Ipp64f*) ip1, (Ipp64f*) ip2, (Ipp64f*) op, Len );
}

void CDSPRealFFT :: multiplyBlocks( const realfft_t* const ip,
	realfft_t* const op ) const
{
	ippsMulPerm_64f( (Ipp64f*) op, (Ipp64f*) ip, (Ipp64f*) op, Len );
}

void CDSPRealFFT :: multiplyBlocksZP( const realfft_t* ip,
	realfft_t* op ) const
{
	int i;

	for( i = 0; i < Len; i++ )
	{
		op[ i ] *= ip[ i ];
	}
}

void CDSPRealFFT :: convertToZP( realfft_t* const p ) const
{
	int i = 2;

	while( i < Len )
	{
		p[ i + 1 ] = p[ i ];
		i += 2;
	}
}

namespace {

/**
 * Global pool of FFT setup objects and of free FFT objects, indexed by the
 * length's bit count.  Mirrors the upstream static lists.
 */

struct FFTPool
{
	std::mutex mutex;
	std::map< int, CDSPRealFFTSetup* > Setups;
	std::map< int, std::vector< CDSPRealFFT* > > FreeFFTs;

	~FFTPool()
	{
		std :: map< int, CDSPRealFFTSetup* > :: iterator it;

		for( it = Setups.begin(); it != Setups.end(); it++ )
		{
			delete it -> second;
		}

		std :: map< int, std :: vector< CDSPRealFFT* > > :: iterator jt;

		for( jt = FreeFFTs.begin(); jt != FreeFFTs.end(); jt++ )
		{
			std :: vector< CDSPRealFFT* > :: iterator kt;

			for( kt = jt -> second.begin(); kt != jt -> second.end(); kt++ )
			{
				delete *kt;
			}
		}
	}

private:
	FFTPool( const FFTPool& );
	FFTPool& operator = ( const FFTPool& );

public:
	FFTPool()
	{
	}
};

FFTPool& getFFTPool()
{
	static FFTPool Pool;

	return( Pool );
}

} // namespace

CDSPRealFFT* CDSPRealFFTKeeper :: acquire( const int LenBits )
{
	R8BASSERT( LenBits > 0 && LenBits <= 30 );

	FFTPool& p = getFFTPool();
	std :: lock_guard< std :: mutex > lock( p.mutex );

	CDSPRealFFTSetup*& s = p.Setups[ LenBits ];

	if( s == R8B_NULL )
	{
		s = new CDSPRealFFTSetup( LenBits );
	}

	std :: vector< CDSPRealFFT* >& v = p.FreeFFTs[ LenBits ];

	if( v.empty() )
	{
		return( new CDSPRealFFT( s ));
	}

	CDSPRealFFT* const ffto = v.back();
	v.pop_back();

	return( ffto );
}

void CDSPRealFFTKeeper :: release( CDSPRealFFT* const ffto )
{
	FFTPool& p = getFFTPool();
	std :: lock_guard< std :: mutex > lock( p.mutex );

	p.FreeFFTs[ ffto -> getLenBits() ].push_back( ffto );
}

CDSPRealFFTKeeper :: CDSPRealFFTKeeper( const int LenBits )
{
	Object = acquire( LenBits );
}

CDSPRealFFTKeeper :: ~CDSPRealFFTKeeper()
{
	if( Object != R8B_NULL )
	{
		release( Object );
	}
}

void CDSPRealFFTKeeper :: init( const int LenBits )
{
	if( Object != R8B_NULL )
	{
		if( Object -> getLenBits() == LenBits )
		{
			return;
		}

		release( Object );
	}

	Object = acquire( LenBits );
}

void CDSPRealFFTKeeper :: reset()
{
	if( Object != R8B_NULL )
	{
		release( Object );
		Object = R8B_NULL;
	}
}

} // namespace r8b