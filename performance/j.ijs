
work_py =: 4.0589278 2.7004840 3.8789894 4.2040206 3.8324532 4.1464389 2.8027210 4.1722624
work_ka =: 0.4513751 0.2327353 0.2230273 0.2500368 0.5410698 0.3486846 0.5201439 0.5239287

NB. 8.99236 11.6032 17.3924 16.8136 7.0831 11.8917 5.38836 7.96342
echo work_py % work_ka
echo (+/work_py) % +/work_ka NB. 9.64

exit 0

NB.                    old  7.4
NB. collatz_steps      4.8  9.0
NB. fibonacci         16.3 11.6
NB. primes             7.5 17.4
NB. crc64             16.1 16.8
NB. e,pi               8.7  7.1
NB. mandelbrot        11.0 11.9
NB. phys.simulation    6.4  5.4
NB. finance            6.9  8.0

