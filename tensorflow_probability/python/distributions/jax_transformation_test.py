# Copyright 2020 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""Tests TFP distribution compositionality with JAX transformations."""
import functools

from absl.testing import parameterized
import hypothesis as hp
from hypothesis import strategies as hps
import jax
from jax import random
import jax.numpy as np

# pylint: disable=no-name-in-module

from tensorflow_probability.python.distributions._jax import hypothesis_testlib as dhps
from tensorflow_probability.python.experimental.substrates.jax import tf2jax as tf
from tensorflow_probability.python.internal._jax import hypothesis_testlib as tfp_hps
from tensorflow_probability.python.internal._jax import test_util

JIT_SAMPLE_BLOCKLIST = set()
JIT_LOGPROB_BLOCKLIST = set()

VMAP_SAMPLE_BLOCKLIST = set()
VMAP_LOGPROB_BLOCKLIST = set()

JVP_SAMPLE_BLOCKLIST = set()
JVP_LOGPROB_SAMPLE_BLOCKLIST = set()
JVP_LOGPROB_PARAM_BLOCKLIST = set()

VJP_SAMPLE_BLOCKLIST = set()
VJP_LOGPROB_SAMPLE_BLOCKLIST = set()
VJP_LOGPROB_PARAM_BLOCKLIST = set()

test_all_distributions = parameterized.named_parameters(
    {'testcase_name': dname, 'dist_name': dname} for dname in
    sorted(list(dhps.INSTANTIABLE_BASE_DISTS.keys())
           + list(dhps.INSTANTIABLE_META_DISTS)))

test_base_distributions = parameterized.named_parameters(
    {'testcase_name': dname, 'dist_name': dname} for dname in
    sorted(list(dhps.INSTANTIABLE_BASE_DISTS.keys())))


class JitTest(test_util.TestCase):

  @test_all_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testSample(self, dist_name, data):
    if dist_name in JIT_SAMPLE_BLOCKLIST:
      self.skipTest('Distribution currently broken.')
    dist = data.draw(dhps.distributions(enable_vars=False,
                                        dist_name=dist_name))
    def _sample(seed):
      return dist.sample(seed=seed)
    seed = test_util.test_seed()
    self.assertAllClose(_sample(seed), jax.jit(_sample)(seed), rtol=1e-6,
                        atol=1e-6)

  @test_all_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testLogProb(self, dist_name, data):
    if dist_name in JIT_LOGPROB_BLOCKLIST:
      self.skipTest('Distribution currently broken.')
    dist = data.draw(dhps.distributions(enable_vars=False,
                                        dist_name=dist_name))
    sample = dist.sample(seed=test_util.test_seed())
    self.assertAllClose(dist.log_prob(sample), jax.jit(dist.log_prob)(sample),
                        rtol=1e-6, atol=1e-6)


class VmapTest(test_util.TestCase):

  @test_all_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testSample(self, dist_name, data):
    if dist_name in VMAP_SAMPLE_BLOCKLIST:
      self.skipTest('Distribution currently broken.')
    dist = data.draw(dhps.distributions(enable_vars=False,
                                        dist_name=dist_name))
    def _sample(seed):
      return dist.sample(seed=seed)
    seed = test_util.test_seed()
    jax.vmap(_sample)(random.split(seed, 10))

  @test_all_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testLogProb(self, dist_name, data):
    if dist_name in VMAP_LOGPROB_BLOCKLIST:
      self.skipTest('Distribution currently broken.')
    dist = data.draw(dhps.distributions(enable_vars=False,
                                        dist_name=dist_name))
    sample = dist.sample(seed=test_util.test_seed(), sample_shape=10)
    self.assertAllClose(jax.vmap(dist.log_prob)(sample), dist.log_prob(sample),
                        rtol=1e-6, atol=1e-6)


class _GradTest(test_util.TestCase):

  def _make_distribution(self, dist_name, params,
                         batch_shape, override_params=None):
    override_params = override_params or {}
    all_params = dict(params)
    for param_name, override_param in override_params.items():
      all_params[param_name] = override_param
    all_params = dhps.constrain_params(all_params, dist_name)
    all_params = dhps.modify_params(all_params, dist_name, validate_args=False)
    return dhps.base_distributions(
        enable_vars=False, dist_name=dist_name, params=all_params,
        batch_shape=batch_shape, validate_args=False)

  def _param_func_generator(self, data, dist_name, params, batch_shape, func,
                            generate_sample_function=False):
    for param_name, param in params.items():
      if (not tf.is_tensor(param)
          or not np.issubdtype(param.dtype, np.floating)):
        continue
      def _func(param_name, param):
        dist = data.draw(self._make_distribution(
            dist_name, params, batch_shape,
            override_params={param_name: param}))
        return func(dist)
      yield param_name, param, _func

  @test_base_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testSample(self, dist_name, data):
    if dist_name in JVP_SAMPLE_BLOCKLIST:
      self.skipTest('Distribution currently broken.')

    def _sample(dist):
      return dist.sample(seed=random.PRNGKey(0))

    params_unconstrained, batch_shape = data.draw(
        dhps.base_distribution_unconstrained_params(
            enable_vars=False, dist_name=dist_name))

    for param_name, unconstrained_param, func in self._param_func_generator(
        data, dist_name, params_unconstrained, batch_shape, _sample):
      self._test_transformation(
          functools.partial(func, param_name), unconstrained_param,
          msg=param_name)

  @test_base_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testLogProbParam(self, dist_name, data):
    if dist_name in self.logprob_param_blocklist:
      self.skipTest('Distribution currently broken.')

    params, batch_shape = data.draw(
        dhps.base_distribution_unconstrained_params(
            enable_vars=False, dist_name=dist_name))
    constrained_params = dhps.constrain_params(params, dist_name)

    sampling_dist = data.draw(dhps.base_distributions(
        batch_shape=batch_shape, enable_vars=False, dist_name=dist_name,
        params=constrained_params))
    sample = sampling_dist.sample(seed=random.PRNGKey(0))
    def _log_prob(dist):
      return dist.log_prob(sample)
    for param_name, param, func in self._param_func_generator(
        data, dist_name, params, batch_shape, _log_prob):
      self._test_transformation(
          functools.partial(func, param_name), param, msg=param_name)

  @test_base_distributions
  @hp.given(hps.data())
  @tfp_hps.tfp_hp_settings()
  def testLogProbSample(self, dist_name, data):
    if dist_name in self.logprob_sample_blocklist:
      self.skipTest('Distribution currently broken.')

    params, batch_shape = data.draw(
        dhps.base_distribution_params(enable_vars=False, dist_name=dist_name,
                                      constrain_params=True))

    dist = data.draw(dhps.base_distributions(
        enable_vars=False, dist_name=dist_name, params=params,
        batch_shape=batch_shape, validate_args=False))
    sample = dist.sample(seed=random.PRNGKey(0))
    def _log_prob(sample):
      return dist.log_prob(sample)
    self._test_transformation(_log_prob, sample)


class JVPTest(_GradTest):

  sample_blocklist = JVP_SAMPLE_BLOCKLIST
  logprob_param_blocklist = JVP_LOGPROB_PARAM_BLOCKLIST
  logprob_sample_blocklist = JVP_LOGPROB_SAMPLE_BLOCKLIST

  def _test_transformation(self, func, param, msg=None):
    _, jvp = jax.jvp(func, (param,), (np.ones_like(param),))
    self.assertNotAllEqual(jvp, np.zeros_like(jvp), msg=msg)


class VJPTest(_GradTest):

  sample_blocklist = VJP_SAMPLE_BLOCKLIST
  logprob_param_blocklist = VJP_LOGPROB_PARAM_BLOCKLIST
  logprob_sample_blocklist = VJP_LOGPROB_SAMPLE_BLOCKLIST

  def _test_transformation(self, func, param, msg=None):
    out, f_vjp = jax.vjp(func, param)
    vjp, = f_vjp(np.ones_like(out).astype(out.dtype))
    self.assertNotAllEqual(vjp, np.zeros_like(vjp), msg=msg)


if __name__ == '__main__':
  tf.test.main()
