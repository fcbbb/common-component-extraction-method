//$ nobt
//$ nocpp

/**
 * @file CDSPRealFFT.h
 *
 * @brief Real-valued FFT transform class.
 *
 * Component extraction of r8brain-free-src's real-valued FFT wrapper.  The
 * public interface -- CDSPRealFFTSetup, CDSPRealFFT, CDSPRealFFTKeeper and
 * calcMinPhaseTransform() -- is the upstream one.  What differs from the
 * upstream file is only the packaging: the backend-specific state (the IPP
 * specification buffer and the work buffer) lives behind an opaque pointer
 * that the implementation file defines, so this header contains no backend
 * types.  The upstream file also carries the PFFFT and Ooura branches; here
 * only the IPP branch is kept, since that is the code under migration.
 *
 * FFT blocks handled by this class use the "Perm" (real-permuted) layout:
 *
 *   p[0]        = Re X[0]
 *   p[1]        = Re X[N/2]
 *   p[2*k]      = Re X[k]     for k = 1 .. N/2-1
 *   p[2*k + 1]  = Im X[k]     for k = 1 .. N/2-1
 *
 * There is no scaling: the inverse transform returns N times the input.
 * getInvMulConst() returns the 1/N factor that callers apply afterwards.
 *
 * r8brain-free-src Copyright (c) 2013-2026 Aleksey Vaneev
 *
 * See the "LICENSE" file for license.
 */

#ifndef R8B_CDSPREALFFT_INCLUDED
#define R8B_CDSPREALFFT_INCLUDED

#include "r8bbase.h"

namespace r8b {

typedef double realfft_t; ///< Forward transform's native type.

/**
 * @brief Real-valued FFT setup class.
 *
 * This class stores pre-calculated data for FFT functions of a specific
 * length. Only a single object of this class is required for all FFT
 * transform objects utilized concurrently.
 */

class CDSPRealFFTSetup : public R8B_BASECLASS
{
	R8BNOCTOR( CDSPRealFFTSetup )

	friend class CDSPRealFFT;
	friend class CDSPRealFFTKeeper;

public:
	/**
	 * @brief Return a multiplication constant that should be used after
	 * inverse transform to obtain a correct value scale.
	 */

	double getInvMulConst() const
	{
		return( InvMulConst );
	}

	/**
	 * @brief Returns the length (the number of real values in a transform) of
	 * *this* FFT setup object, expressed as Nth power of 2.
	 */

	int getLenBits() const
	{
		return( LenBits );
	}

	/**
	 * @brief Returns the length (the number of real values in a transform) of
	 * *this* FFT setup object.
	 */

	int getLen() const
	{
		return( Len );
	}

	~CDSPRealFFTSetup();

private:
	int LenBits; ///< Length of FFT block (expressed as Nth power of 2).
	int Len; ///< Length of FFT block (number of real values).
	double InvMulConst; ///< Inverse FFT multiply constant.

	struct Spec; ///< Backend-specific specification (defined in the .cpp).
	Spec* spec; ///< Spec pointer.

	/**
	 * @brief Initializes *this* FFT setup object.
	 *
	 * @param aLenBits The length of FFT block (Nth power of 2), specifies the
	 * number of real values in a block. Values from 1 to 30 inclusive are
	 * supported.
	 */

	CDSPRealFFTSetup( const int aLenBits );
};

/**
 * @brief Real-valued FFT transform class.
 *
 * Class implements a wrapper for real-valued discrete fast Fourier transform
 * functions. The object of this class can only be obtained via the
 * CDSPRealFFTKeeper class.
 *
 * As a general pre-condition, the buffers passed to the functions of this
 * class should be aligned to 32 bytes.
 */

class CDSPRealFFT : public R8B_BASECLASS
{
	R8BNOCTOR( CDSPRealFFT )

	friend class CDSPRealFFTKeeper;

public:
	/**
	 * @brief Return a multiplication constant that should be used after
	 * inverse transform to obtain a correct value scale.
	 */

	double getInvMulConst() const
	{
		return( s -> InvMulConst );
	}

	/**
	 * @brief Returns the length (the number of real values in a transform) of
	 * *this* FFT object, expressed as Nth power of 2.
	 */

	int getLenBits() const
	{
		return( s -> LenBits );
	}

	/**
	 * @brief Returns the length (the number of real values in a transform) of
	 * *this* FFT object.
	 */

	int getLen() const
	{
		return( Len );
	}

	/**
	 * @brief Performs in-place forward FFT.
	 *
	 * @param[in,out] p Pointer to data block to transform, length should be
	 * equal to *this* object's getLen().
	 * @return The pointer `p` casted to transform's native type.
	 */

	realfft_t* forward( double* const p ) const;

	/**
	 * @brief Performs in-place inverse FFT.
	 *
	 * @param[in,out] p Pointer to data block to transform, length should be
	 * equal to *this* object's getLen().
	 */

	void inverse( realfft_t* const p ) const;

	/**
	 * @brief Returns pointer to the internal work buffer.
	 *
	 * This buffer can be used for FFT bin reordering.
	 *
	 * @return The work buffer pointer, or `nullptr` if FFT produces
	 * sequential-ordered FFT bins.
	 */

	realfft_t* getWorkBuf() const
	{
		return( R8B_NULL );
	}

	/**
	 * @brief Reorders FFT bins from native ordering (after the forward
	 * transform) to sequential ordering.
	 *
	 * @param p Input FFT block.
	 * @param op Output FFT block.
	 * @return The pointer to the reordered FFT block. May return `p` if the
	 * transform has sequential ordering already.
	 */

	realfft_t* reorderForward( realfft_t* const p,
		realfft_t* const op ) const
	{
		(void) op;

		return( p );
	}

	/**
	 * @brief Reorders FFT bins from sequential ordering (before the inverse
	 * transform) to native ordering.
	 *
	 * @param ip Pointer to FFT block (previously returned by the
	 * reorderForward() function).
	 * @param op Output FFT block (may equal `ip`).
	 * @return The pointer to the reordered FFT block (`op` casted to the
	 * `realfft_t` type).
	 */

	realfft_t* reorderInverse( const realfft_t* const ip,
		double* const op ) const
	{
		if( ip != op )
		{
			memcpy( op, ip, (size_t) Len * sizeof( double ));
		}

		return( op );
	}

	/**
	 * @brief Replaces the Nyquist FFT bin in the specified block.
	 *
	 * @param p Pointer to FFT block.
	 * @param v New Nyquist bin value.
	 */

	static void setBinNyquist( realfft_t* const p, const realfft_t v )
	{
		p[ 1 ] = v;
	}

	/**
	 * @brief Multiplies two complex-valued data blocks and places result in
	 * a new data block.
	 *
	 * Length of all data blocks should be equal to *this* object's block
	 * length. Input blocks should have been produced with the forward()
	 * function of *this* object.
	 *
	 * @param ip1 Input FFT block 1.
	 * @param ip2 Input FFT block 2.
	 * @param[out] op Output FFT block, should not be equal to `ip1` nor
	 * `ip2`.
	 */

	void multiplyBlocks( const realfft_t* const ip1,
		const realfft_t* const ip2, realfft_t* const op ) const;

	/**
	 * @brief Multiplies two complex-valued FFT blocks in-place.
	 *
	 * Length of both blocks should be equal to *this* object's block length.
	 * Blocks should have been produced with the forward() function of *this*
	 * object.
	 *
	 * @param ip Input FFT block 1.
	 * @param[in,out] op Output/input FFT block 2.
	 */

	void multiplyBlocks( const realfft_t* const ip,
		realfft_t* const op ) const;

	/**
	 * @brief Multiplies two complex-valued FFT blocks in-place, considering
	 * that the `ip` block contains "zero-phase" response.
	 *
	 * Length of both blocks should be equal to *this* object's block length.
	 * Blocks should have been produced with the forward() function of *this*
	 * object.
	 *
	 * @param ip Input FFT block 1, "zero-phase" response. This block should
	 * be first transformed via the convertToZP() function.
	 * @param[in,out] op Output/input FFT block 2.
	 */

	void multiplyBlocksZP( const realfft_t* ip, realfft_t* op ) const;

	/**
	 * @brief Converts the specified forward-transformed FFT block into
	 * "zero-phase" form, suitable for use with the multiplyBlocksZP()
	 * function.
	 *
	 * @param[in,out] p Block to transform.
	 */

	void convertToZP( realfft_t* const p ) const;

	~CDSPRealFFT();

private:
	const CDSPRealFFTSetup* s; ///< Pointer to static FFT transform setup
		///< object.
	int Len; ///< Length of FFT block (number of real values).

	struct Work; ///< Backend-specific work buffer (defined in the .cpp).
	Work* work; ///< Work pointer.

	/**
	 * Constructor initializes FFT object.
	 *
	 * @param s0 Pointer to FFT setup object.
	 */

	CDSPRealFFT( const CDSPRealFFTSetup* const s0 );
};

/**
 * @brief A "keeper" class for real-valued FFT transform objects.
 *
 * Class implements "keeper" functionality for handling CDSPRealFFT objects.
 * The allocated FFT objects are placed on the global static list of objects
 * for future reuse instead of deallocation.
 */

class CDSPRealFFTKeeper : public R8B_BASECLASS
{
	R8BNOCTOR( CDSPRealFFTKeeper )

public:
	CDSPRealFFTKeeper()
		: Object( R8B_NULL )
	{
	}

	/**
	 * @brief Acquires FFT object with the specified block length.
	 *
	 * @param LenBits The length of FFT block (Nth power of 2), in the range
	 * [1; 30] inclusive, specifies the number of real values in a FFT block.
	 */

	CDSPRealFFTKeeper( const int LenBits );

	~CDSPRealFFTKeeper();

	/**
	 * @brief Returns pointer to the acquired FFT object.
	 */

	const CDSPRealFFT* operator -> () const
	{
		R8BASSERT( Object != R8B_NULL );

		return( Object );
	}

	/**
	 * @brief Acquires FFT object with the specified block length. This
	 * function can be called any number of times.
	 *
	 * @param LenBits The length of FFT block (Nth power of 2), in the range
	 * [1; 30] inclusive, specifies the number of real values in a FFT block.
	 */

	void init( const int LenBits );

	/**
	 * @brief Releases a previously acquired FFT object.
	 */

	void reset();

private:
	CDSPRealFFT* Object; ///< FFT object.

	/**
	 * @brief Acquires FFT object from the global pool.
	 *
	 * @param LenBits FFT block length (expressed as Nth power of 2).
	 */

	static CDSPRealFFT* acquire( const int LenBits );

	/**
	 * @brief Releases a previously acquired FFT object.
	 *
	 * @param ffto FFT object to release.
	 */

	static void release( CDSPRealFFT* const ffto );
};

/**
 * @brief Calculates the minimum-phase transform of the filter kernel, using
 * a discrete Hilbert transform in cepstrum domain.
 *
 * For more details, see part III.B of
 * http://www.hpl.hp.com/personal/Niranjan_Damera-Venkata/files/ComplexMinPhase.pdf
 *
 * @param[in,out] Kernel Filter kernel buffer.
 * @param KernelLen Filter kernel's length, in samples.
 * @param LenMult Kernel length multiplier. Used as a coefficient of
 * oversampling in the frequency domain. Such oversampling is needed to
 * improve the precision of the minimum-phase transform. If the filter's
 * attenuation is high, this multiplier should be increased or otherwise the
 * required attenuation will not be reached due to "smoothing" effect of this
 * transform.
 * @param DoFinalMul `true` if the final multiplication after transform
 * should be performed. Such multiplication returns the gain of the signal to
 * its original value. This parameter can be set to `false` if normalization
 * of the resulting filter kernel is planned to be used.
 * @param[out] DCGroupDelay If not `nullptr`, this variable receives group
 * delay at DC offset, in samples (can be a non-integer value).
 */

inline void calcMinPhaseTransform( double* const Kernel, const int KernelLen,
	const int LenMult = 2, const bool DoFinalMul = true,
	double* const DCGroupDelay = R8B_NULL )
{
	R8BASSERT( KernelLen > 0 );
	R8BASSERT( LenMult >= 2 );

	const int LenBits = getBitOccupancy(( KernelLen * LenMult ) - 1 );
	const int Len = 1 << LenBits;
	const int Len2 = Len >> 1;
	int i;

	CFixedBuffer< double > ip( Len );
	CFixedBuffer< realfft_t > ip2( Len2 + 1 );

	memcpy( &ip[ 0 ], Kernel, (size_t) KernelLen * sizeof( ip[ 0 ]));
	memset( &ip[ KernelLen ], 0,
		(size_t) ( Len - KernelLen ) * sizeof( ip[ 0 ]));

	CDSPRealFFTKeeper ffto( LenBits );

	realfft_t* aip = ffto -> reorderForward( ffto -> forward( ip ),
		ffto -> getWorkBuf() );

	realfft_t* const aip2 = &ip2[ 0 ];

	const realfft_t nzbias = ( sizeof( realfft_t ) < sizeof( double ) ?
		1e-35 : 1e-300 );

	// Create the "log |c|" spectrum while saving the original power spectrum
	// in the "ip2" buffer.

	aip2[ 0 ] = aip[ 0 ];
	aip[ 0 ] = log( fabs( aip[ 0 ]) + nzbias );
	aip2[ Len2 ] = aip[ 1 ];
	aip[ 1 ] = log( fabs( aip[ 1 ]) + nzbias );

	for( i = 1; i < Len2; i++ )
	{
		aip2[ i ] = sqrt( aip[ i * 2 ] * aip[ i * 2 ] +
			aip[ i * 2 + 1 ] * aip[ i * 2 + 1 ]);

		aip[ i * 2 ] = log( aip2[ i ] + nzbias );
		aip[ i * 2 + 1 ] = 0.0;
	}

	// Convert to cepstrum and apply discrete Hilbert transform.

	ffto -> inverse( ffto -> reorderInverse( aip, ip ));

	const double m1 = ffto -> getInvMulConst();
	const double m2 = -m1;

	ip[ 0 ] = 0.0;

	for( i = 1; i < Len2; i++ )
	{
		ip[ i ] *= m1;
	}

	ip[ Len2 ] = 0.0;

	for( i = Len2 + 1; i < Len; i++ )
	{
		ip[ i ] *= m2;
	}

	// Convert Hilbert-transformed cepstrum back to the "log |c|" spectrum and
	// perform its exponentiation, multiplied by the power spectrum previously
	// saved in the "ip2" buffer.

	aip = ffto -> reorderForward( ffto -> forward( ip ),
		ffto -> getWorkBuf() );

	aip[ 0 ] = aip2[ 0 ];
	aip[ 1 ] = aip2[ Len2 ];

	for( i = 1; i < Len2; i++ )
	{
		aip[ i * 2 + 0 ] = cos( aip[ i * 2 + 1 ]) * aip2[ i ];
		aip[ i * 2 + 1 ] = sin( aip[ i * 2 + 1 ]) * aip2[ i ];
	}

	ffto -> inverse( ffto -> reorderInverse( aip, ip ));

	if( DoFinalMul )
	{
		for( i = 0; i < KernelLen; i++ )
		{
			Kernel[ i ] = ip[ i ] * m1;
		}
	}
	else
	{
		memcpy( &Kernel[ 0 ], &ip[ 0 ],
			(size_t) KernelLen * sizeof( Kernel[ 0 ]));
	}

	if( DCGroupDelay != R8B_NULL )
	{
		*DCGroupDelay = calcFIRFilterGroupDelay( Kernel, KernelLen, 0.0 );
	}
}

} // namespace r8b

#endif // R8B_CDSPREALFFT_INCLUDED